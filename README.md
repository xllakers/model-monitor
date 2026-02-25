# LLM Monitor

Local dashboard tracking fast risers and new stars on the [LM Arena leaderboard](https://arena.ai/leaderboard).

## What it shows

- **Fast Risers** — models with the biggest rank improvement over the past 7 days (general + coding)
- **New Stars** — models now in top-30 that weren't in the top-50 ~30 days ago
- **Full Rankings** — general and coding tabs with ELO score, rank delta, price, OpenRouter usage rank

## Sources

| Source | Data | Access |
|---|---|---|
| [arena.ai](https://arena.ai/leaderboard) | ELO scores, current rankings (general + coding) | Scraped |
| [Wayback Machine](https://web.archive.org) | Historical rank snapshots for 7d/30d deltas | Scraped |
| [OpenRouter](https://openrouter.ai) | Price/1M tokens (input + output), weekly usage rank | Free API + page scrape |

> **Note:** Days in Board is calculated using the creation timestamp from the OpenRouter API.

## Setup

```bash
pip install -r requirements.txt
python3 backfill.py   # one-time: pull historical snapshots to populate deltas
python3 app.py
# open http://localhost:5000
```

## Backfill

Run `backfill.py` once before starting the server. It fetches:
1. **Current live data** from arena.ai (`/leaderboard/text`, `/leaderboard/code`)
2. **7-day-ago snapshot** from the Wayback Machine → used for fast-riser rank deltas
3. **30-day-ago snapshot** (or earliest available) → used for new-star detection

```bash
python3 backfill.py
# Output:
# Fetching current live data...
#   general: 314 models, #1=claude-opus-4-6
#   coding: 45 models, #1=claude-opus-4-6
# Fetching ~7 days ago snapshot...
#   Fetching 7d ago: http://web.archive.org/web/...
#   Parsed: general=307, coding=303 models
# Fetching ~30 days ago snapshot...
#   Fetching 27d ago: http://web.archive.org/web/...
#   Parsed: general=299, coding=295 models
```

Re-run backfill any time you want to reset the historical baseline (e.g. weekly).

## Cache

Page loads use a 2-hour local cache (`data/`). Delete `data/*.json` and reload to force a fresh fetch.

## Structure

```
app.py                        # Flask entry point
fetchers/
  lmarena.py                  # Scrape arena.ai for current ELO rankings
  artificial_analysis.py      # Stub (AA API key required for speed data)
  openrouter.py               # OR /api/v1/models (pricing) + /rankings (usage)
analyzer.py                   # Rank delta, fast risers, new stars, signal merge
backfill.py                   # One-time historical backfill from Wayback Machine
templates/index.html          # Single-page dashboard
data/                         # Cache files (gitignored)
```
