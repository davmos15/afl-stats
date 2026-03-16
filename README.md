# AFL Stats Search

**[Try it live](https://davmos15.github.io/afl-stats/)**

Natural language search for AFL statistics. Ask questions in plain English and get instant answers with data tables, charts, and R code.

Powered by live data from [Squiggle](https://squiggle.com.au) and [AFL Tables](https://afltables.com), with AI from your choice of Google Gemini or OpenAI.

## Features

- **Natural language queries** - "Who kicked the most goals in 2025?", "Last 5 Grand Final winners"
- **Live data** - current season standings, match results, and player stats via Squiggle API and AFL Tables
- **Multiple AI providers** - Google Gemini (free) or OpenAI
- **Data tables + charts** - toggle between table, bar chart, and column chart views
- **R code** - every answer includes fitzRoy R code to reproduce the analysis
- **Dark mode** - automatic or manual light/dark theme
- **Usage tracking** - see daily request/token usage against free tier limits
- **No server-side key storage** - API keys are stored in your browser's localStorage

## Quick Start

```bash
git clone https://github.com/davmos15/afl-stats.git
cd afl-stats
pip install -r requirements.txt
python main.py
```

Visit [http://localhost:8000](http://localhost:8000), click the AI selector, paste your API key, and start searching.

### Docker

```bash
docker compose up --build
```

## Getting an API Key

You need an API key from at least one provider. **Google Gemini is recommended** - it's free and has generous limits.

### Google Gemini (Free)

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Sign in with your Google account
3. Click **Create API Key**
4. Copy the key and paste it in the app's AI settings

Free tier: 1,500 requests/day, 1M tokens/day. Resets at midnight Pacific Time.

### OpenAI (Paid)

1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Create an account or sign in
3. Click **Create new secret key**
4. Copy the key

Requires adding credits to your account ($5 minimum). Uses `gpt-4o-mini`.

### Anthropic Claude (Paid)

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an account or sign in
3. Navigate to **Settings > API Keys**
4. Click **Create Key**

Requires adding credits to your account ($5 minimum). Uses `claude-sonnet-4`.

## Configuration

API keys can be entered in two ways:

1. **In the browser** (recommended) - click the AI selector below the search bar and paste your key. Keys are stored in your browser's localStorage and never sent to any server besides the AI provider.

2. **Environment variables** - copy `.env.example` to `.env` and set your keys:

```bash
cp .env.example .env
```

## API Endpoints

| Method | Path       | Description                        |
|--------|------------|------------------------------------|
| GET    | `/`        | Main search page                   |
| POST   | `/search`  | Submit a query (returns HTML fragment) |
| GET    | `/healthz` | Health check                       |

## Data Sources

| Source | Data | Update Frequency |
|--------|------|-----------------|
| [Squiggle API](https://squiggle.com.au) | Ladder, match results, Grand Finals | Live (cached 5 min) |
| [AFL Tables](https://afltables.com) | Player stats (goals, disposals, etc.) | Daily (cached 15 min) |
| AI model knowledge | Historical records, all-time stats | Training data cutoff |

## Tech Stack

- **Backend** - Python 3.12, FastAPI, Uvicorn
- **Frontend** - Tailwind CSS, HTMX, Chart.js (lazy-loaded)
- **AI** - Google Gemini 2.5 Flash / OpenAI GPT-4o-mini / Claude Sonnet 4
- **Data** - Squiggle API, AFL Tables

## Project Structure

```
main.py                    # FastAPI app, LLM provider logic
data.py                    # Squiggle API + AFL Tables scraper
prompts/r_code.tmpl        # LLM prompt template
templates/
  index.html               # Main page (search, AI settings, dark mode)
  partials/results.html    # HTMX results fragment (table, charts)
tests/test_main.py         # Tests
requirements.txt           # Python dependencies
Dockerfile                 # Container config
docker-compose.yml         # Docker Compose
```

## Running Tests

```bash
pip install pytest
pytest tests/
```

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run with auto-reload
python main.py

# The server watches for file changes and reloads automatically
```

## License

MIT
