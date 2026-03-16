"""Scrape player stats from AFL Tables and save as JSON for GitHub Pages."""

import json
import os
import sys
from datetime import datetime
from urllib.request import urlopen, Request
from html.parser import HTMLParser


class AFLTableParser(HTMLParser):
    """Parse AFL Tables player stats HTML into structured data."""

    def __init__(self):
        super().__init__()
        self.players = []
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_row = []
        self.current_cell = ""
        self.headers = []
        self.team_name = ""
        self.row_count = 0
        self.tables_found = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
            self.headers = []
            self.row_count = 0
            self.tables_found += 1
        elif tag == "tr" and self.in_table:
            self.in_row = True
            self.current_row = []
            self.current_cell = ""
        elif tag in ("td", "th") and self.in_row:
            self.in_cell = True
            self.current_cell = ""

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False
        elif tag == "tr" and self.in_row:
            self.in_row = False
            self.row_count += 1
            if self.row_count == 1:
                self.team_name = " ".join(self.current_row).split("[")[0].strip()
            elif self.row_count == 2:
                self.headers = [c.strip() for c in self.current_row]
            elif self.headers and "Player" in self.headers:
                self._add_player()
        elif tag in ("td", "th") and self.in_cell:
            self.in_cell = False
            self.current_row.append(self.current_cell.strip())

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data

    def _add_player(self):
        if len(self.current_row) < len(self.headers):
            return
        col = {h: i for i, h in enumerate(self.headers)}
        try:
            self.players.append({
                "player": self.current_row[col.get("Player", 1)],
                "team": self.team_name,
                "games": _safe_int(self.current_row, col, "GM"),
                "kicks": _safe_int(self.current_row, col, "KI"),
                "marks": _safe_int(self.current_row, col, "MK"),
                "handballs": _safe_int(self.current_row, col, "HB"),
                "disposals": _safe_int(self.current_row, col, "DI"),
                "goals": _safe_int(self.current_row, col, "GL"),
                "behinds": _safe_int(self.current_row, col, "BH"),
                "tackles": _safe_int(self.current_row, col, "TK"),
            })
        except (IndexError, ValueError):
            pass


def _safe_int(cells, col_map, key):
    idx = col_map.get(key)
    if idx is None or idx >= len(cells):
        return 0
    try:
        return int(cells[idx].strip())
    except ValueError:
        return 0


def scrape_year(year):
    url = f"https://afltables.com/afl/stats/{year}.html"
    req = Request(url, headers={"User-Agent": "AFL-Stats-Search/1.0"})
    try:
        with urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Failed to fetch {year}: {e}")
        return []

    parser = AFLTableParser()
    parser.feed(html)
    print(f"  {year}: {len(parser.players)} players from {parser.tables_found} tables")
    return parser.players


def main():
    current_year = datetime.now().year
    years = [current_year - 1, current_year]

    output = {}
    for year in years:
        print(f"Scraping {year}...")
        players = scrape_year(year)
        if players:
            output[str(year)] = {
                "players": players,
                "top_goals": sorted(players, key=lambda p: p["goals"], reverse=True)[:25],
                "top_disposals": sorted(players, key=lambda p: p["disposals"], reverse=True)[:25],
                "top_kicks": sorted(players, key=lambda p: p["kicks"], reverse=True)[:25],
                "top_marks": sorted(players, key=lambda p: p["marks"], reverse=True)[:25],
                "top_tackles": sorted(players, key=lambda p: p["tackles"], reverse=True)[:25],
            }

    output["updated"] = datetime.utcnow().isoformat() + "Z"

    out_dir = os.environ.get("OUTPUT_DIR", "docs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "player-stats.json")
    with open(out_path, "w") as f:
        json.dump(output, f, separators=(",", ":"))
    print(f"Wrote {out_path} ({os.path.getsize(out_path)} bytes)")


if __name__ == "__main__":
    main()
