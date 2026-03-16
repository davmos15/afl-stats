"""Live AFL data from Squiggle API and AFL Tables."""

import asyncio
import httpx
import json
import logging
import re
import time
from datetime import datetime
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SQUIGGLE_BASE = "https://api.squiggle.com.au/"
AFLTABLES_STATS = "https://afltables.com/afl/stats/{year}.html"
HEADERS = {"User-Agent": "AFL-Stats-Search/1.0 (github.com/afl-stats)"}

FINALS_NAMES = {
    0: "Grand Final",
    1: "Preliminary Final",
    2: "Semi Final",
    3: "Qualifying/Elimination Final",
}

# Cache: key -> (timestamp, data)
_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL_SQUIGGLE = 300  # 5 min
CACHE_TTL_AFLTABLES = 900  # 15 min - stats update less frequently

# Shared HTTP client (created lazily)
_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            headers=HEADERS, timeout=15, limits=httpx.Limits(max_connections=10)
        )
    return _client


def _cache_get(key: str, ttl: int):
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < ttl:
        return entry[1]
    return None


def _cache_set(key: str, data):
    _cache[key] = (time.time(), data)


async def query_squiggle(endpoint: str, params: dict | None = None) -> list:
    cache_key = f"sq:{endpoint}:{params}"
    cached = _cache_get(cache_key, CACHE_TTL_SQUIGGLE)
    if cached is not None:
        return cached
    try:
        client = await _get_client()
        req_params = dict(params or {})
        req_params["q"] = endpoint
        response = await client.get(SQUIGGLE_BASE, params=req_params)
        response.raise_for_status()
        result = response.json().get(endpoint, [])
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        logger.warning("Squiggle API error (%s): %s", endpoint, e)
        return []


async def get_standings(year: int) -> list:
    return await query_squiggle("standings", {"year": year})


async def get_games(year: int) -> list:
    return await query_squiggle("games", {"year": year})


async def get_player_stats(year: int) -> list[dict]:
    """Scrape player stats from AFL Tables (cached)."""
    cache_key = f"aft:{year}"
    cached = _cache_get(cache_key, CACHE_TTL_AFLTABLES)
    if cached is not None:
        return cached

    url = AFLTABLES_STATS.format(year=year)
    try:
        client = await _get_client()
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        all_players = []

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 3:
                continue
            team_row = rows[0].get_text(strip=True)
            header_cells = [c.get_text(strip=True) for c in rows[1].find_all(["th", "td"])]
            if "Player" not in header_cells:
                continue

            col_map = {h: i for i, h in enumerate(header_cells)}
            team_name = team_row.split("[")[0].strip()

            for row in rows[2:]:
                cells = [c.get_text(strip=True) for c in row.find_all("td")]
                if len(cells) < len(header_cells):
                    continue
                try:
                    all_players.append({
                        "player": cells[col_map.get("Player", 1)],
                        "team": team_name,
                        "games": _int(cells, col_map, "GM"),
                        "kicks": _int(cells, col_map, "KI"),
                        "marks": _int(cells, col_map, "MK"),
                        "handballs": _int(cells, col_map, "HB"),
                        "disposals": _int(cells, col_map, "DI"),
                        "goals": _int(cells, col_map, "GL"),
                        "behinds": _int(cells, col_map, "BH"),
                        "tackles": _int(cells, col_map, "TK"),
                    })
                except (IndexError, ValueError):
                    continue

        _cache_set(cache_key, all_players)
        return all_players
    except Exception as e:
        logger.warning("AFL Tables scrape failed for %d: %s", year, e)
        return []


def _int(cells: list, col_map: dict, key: str) -> int:
    idx = col_map.get(key)
    if idx is None or idx >= len(cells):
        return 0
    try:
        return int(cells[idx].strip())
    except ValueError:
        return 0


def _label_game(game: dict) -> dict:
    """Format a game dict for display. Only label finals using the is_final flag."""
    rnd = game.get("round", 0)
    is_final = game.get("is_final", 0)
    label = ""
    if is_final:
        label = "Final"
    return {
        "round": rnd, "label": label,
        "home": game.get("hteam"), "home_score": game.get("hscore"),
        "away": game.get("ateam"), "away_score": game.get("ascore"),
        "winner": game.get("winner"), "date": str(game.get("date", ""))[:10],
    }


async def fetch_live_context(query: str) -> str:
    """Fetch relevant live AFL data based on the user's query."""
    current_year = datetime.now().year
    lower = query.lower()

    # Determine which year(s) to fetch
    years_to_fetch = set()
    for y in range(2012, current_year + 1):
        if str(y) in lower:
            years_to_fetch.add(y)

    # Parse "since YYYY" / "from YYYY" / "after YYYY"
    range_match = re.search(r"(?:since|from|after)\s+(20[12]\d)", lower)
    if range_match:
        start_year = int(range_match.group(1))
        for ry in range(start_year, current_year + 1):
            years_to_fetch.add(ry)

    # Parse "YYYY to YYYY" / "between YYYY and YYYY"
    between_match = re.search(r"(20[12]\d)\s*(?:to|-|and|through)\s*(20[12]\d)", lower)
    if between_match:
        b_start, b_end = int(between_match.group(1)), int(between_match.group(2))
        for by in range(min(b_start, b_end), max(b_start, b_end) + 1):
            years_to_fetch.add(by)

    # Parse "last N years"
    last_n_match = re.search(r"last\s+(\d+)\s+years?", lower)
    if last_n_match:
        n = int(last_n_match.group(1))
        for ly in range(current_year - n + 1, current_year + 1):
            years_to_fetch.add(ly)

    if any(w in lower for w in ["this year", "this season", "current", "latest", "now", "today"]):
        years_to_fetch.add(current_year)
    if "last year" in lower or "last season" in lower:
        years_to_fetch.add(current_year - 1)

    # Default: only current year
    if not years_to_fetch:
        years_to_fetch.add(current_year)

    wants_players = any(
        w in lower
        for w in [
            "goal kicker", "kick", "mark", "handball", "disposal", "tackle",
            "player", "who scored", "who kicked", "top scorer",
            "brownlow", "coleman", "leading", "most goals",
        ]
    )
    wants_team_goals = any(
        w in lower
        for w in [
            "total goals", "team goals", "goals for all", "goals scored",
            "average goals", "goals per",
        ]
    )

    # Fetch all data in parallel
    tasks = {}
    for year in years_to_fetch:
        tasks[f"standings_{year}"] = get_standings(year)
        tasks[f"games_{year}"] = get_games(year)
        if wants_players:
            tasks[f"players_{year}"] = get_player_stats(year)

    keys = list(tasks.keys())
    raw = await asyncio.gather(*tasks.values(), return_exceptions=True)
    results = {k: (v if not isinstance(v, Exception) else []) for k, v in zip(keys, raw)}

    sections = []
    sorted_years = sorted(years_to_fetch)

    # Pre-aggregate team goals across multiple years if requested
    if wants_team_goals and len(sorted_years) > 1:
        team_agg: dict[str, dict] = {}
        for year in sorted_years:
            games = results.get(f"games_{year}", [])
            completed = [g for g in games if g.get("complete") == 100]
            for g in completed:
                ht, at = g.get("hteam"), g.get("ateam")
                for team, gf, ga, bf, ba, pf, pa in [
                    (ht, g.get("hgoals", 0), g.get("agoals", 0), g.get("hbehinds", 0), g.get("abehinds", 0), g.get("hscore", 0), g.get("ascore", 0)),
                    (at, g.get("agoals", 0), g.get("hgoals", 0), g.get("abehinds", 0), g.get("hbehinds", 0), g.get("ascore", 0), g.get("hscore", 0)),
                ]:
                    if team not in team_agg:
                        team_agg[team] = {"goals_for": 0, "goals_against": 0, "behinds_for": 0, "points_for": 0, "points_against": 0, "games": 0}
                    a = team_agg[team]
                    a["goals_for"] += gf; a["goals_against"] += ga
                    a["behinds_for"] += bf
                    a["points_for"] += pf; a["points_against"] += pa
                    a["games"] += 1
        agg_arr = [
            {"team": t, "games": a["games"], "goals_for": a["goals_for"],
             "goals_against": a["goals_against"], "behinds_for": a["behinds_for"],
             "points_for": a["points_for"], "points_against": a["points_against"],
             "avg_goals_per_game": round(a["goals_for"] / a["games"], 2) if a["games"] else 0,
             "avg_points_per_game": round(a["points_for"] / a["games"], 2) if a["games"] else 0}
            for t, a in team_agg.items()
        ]
        agg_arr.sort(key=lambda x: x["goals_for"], reverse=True)
        sections.append(f"=== TEAM GOALS AGGREGATED {sorted_years[0]}-{sorted_years[-1]} ===\n{json.dumps(agg_arr)}")

    for year in sorted_years:
        # Standings
        standings = results.get(f"standings_{year}", [])
        if standings:
            slim = [
                {"rank": s.get("rank"), "team": s.get("name"), "P": s.get("played"),
                 "W": s.get("wins"), "L": s.get("losses"), "D": s.get("draws"),
                 "pts": s.get("pts"), "pct": round(s.get("percentage", 0), 1)}
                for s in standings
            ]
            slim.sort(key=lambda x: x.get("rank") or 99)
            sections.append(f"=== {year} LADDER ===\n{json.dumps(slim)}")

        # Games
        games = results.get(f"games_{year}", [])
        if games:
            completed = [g for g in games if g.get("complete") == 100]
            if completed:
                # For single-year or non-aggregate queries, include recent results
                if not wants_team_goals or len(sorted_years) <= 1:
                    completed.sort(key=lambda g: g.get("date", ""), reverse=True)
                    recent = [_label_game(g) for g in completed[:10]]
                    sections.append(f"=== {year} RECENT RESULTS ===\n{json.dumps(recent)}")

                # For single-year team goal queries, aggregate that year
                if wants_team_goals and len(sorted_years) <= 1:
                    yr_agg: dict[str, dict] = {}
                    for g in completed:
                        ht, at = g.get("hteam"), g.get("ateam")
                        for team, gf, ga, pf, pa in [
                            (ht, g.get("hgoals", 0), g.get("agoals", 0), g.get("hscore", 0), g.get("ascore", 0)),
                            (at, g.get("agoals", 0), g.get("hgoals", 0), g.get("ascore", 0), g.get("hscore", 0)),
                        ]:
                            if team not in yr_agg:
                                yr_agg[team] = {"goals_for": 0, "goals_against": 0, "points_for": 0, "points_against": 0, "games": 0}
                            a = yr_agg[team]
                            a["goals_for"] += gf; a["goals_against"] += ga
                            a["points_for"] += pf; a["points_against"] += pa
                            a["games"] += 1
                    yr_arr = [
                        {"team": t, "games": a["games"], "goals_for": a["goals_for"],
                         "goals_against": a["goals_against"], "points_for": a["points_for"],
                         "points_against": a["points_against"],
                         "avg_goals_per_game": round(a["goals_for"] / a["games"], 2) if a["games"] else 0}
                        for t, a in yr_agg.items()
                    ]
                    yr_arr.sort(key=lambda x: x["goals_for"], reverse=True)
                    sections.append(f"=== {year} TEAM GOALS ===\n{json.dumps(yr_arr)}")

                # Grand Final: only if there are actual finals games
                final_games = [g for g in completed if g.get("is_final", 0)]
                if final_games:
                    gf_round = max(g.get("round", 0) for g in final_games)
                    gf_games = [g for g in final_games if g.get("round") == gf_round]
                    if gf_games:
                        gf = gf_games[0]
                        sections.append(
                            f"=== {year} GRAND FINAL ===\n"
                            f"{gf.get('hteam')} {gf.get('hscore')} vs "
                            f"{gf.get('ateam')} {gf.get('ascore')} "
                            f"- Winner: {gf.get('winner')} "
                            f"(Date: {str(gf.get('date', ''))[:10]})"
                        )

        # Player stats
        if wants_players:
            players = results.get(f"players_{year}", [])
            if players:
                by_goals = sorted(players, key=lambda p: p["goals"], reverse=True)[:15]
                sections.append(
                    f"=== {year} TOP GOAL KICKERS ===\n"
                    + json.dumps([{"player": p["player"], "team": p["team"],
                                   "games": p["games"], "goals": p["goals"]}
                                  for p in by_goals])
                )
                by_disposals = sorted(players, key=lambda p: p["disposals"], reverse=True)[:10]
                sections.append(
                    f"=== {year} TOP DISPOSAL WINNERS ===\n"
                    + json.dumps([{"player": p["player"], "team": p["team"],
                                   "games": p["games"], "disposals": p["disposals"]}
                                  for p in by_disposals])
                )

    if not sections:
        return "(No live data available - answer from your own knowledge)"

    return "\n\n".join(sections)
