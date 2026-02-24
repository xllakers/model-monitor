# LLM Monitor

Local dashboard tracking fast risers and new stars on the [LM Arena leaderboard](https://arena.ai/leaderboard).

## What it shows

- **Fast Risers** — models with the biggest rank improvement over the past 7 days (general + coding)
- **New Stars** — models now in top-30 that weren't in the top-50 a month ago
- **Full Rankings** — general and coding tabs with ELO score, rank delta, price, speed, OpenRouter rank

## Sources

| Source | Data |
|---|---|
| [arena.ai](https://arena.ai/leaderboard) | ELO scores, current rankings (general + coding) |
| [Wayback Machine](https://web.archive.org) | Historical snapshots for 7d/30d deltas |
| Artificial Analysis | Price/1M tokens, speed (tok/s) |
| OpenRouter | Real-world usage rank |

## Setup

```bash
pip install -r requirements.txt
python3 backfill.py   # one-time: fetches historical snapshots for deltas
python3 app.py
# open http://localhost:5000
```

## Cache

Page loads use a 2-hour local cache (`data/`). Delete `data/*.json` and reload to force a fresh fetch.

## Structure

```
app.py                        # Flask entry point
fetchers/
  lmarena.py                  # Scrape arena.ai
  artificial_analysis.py      # AA API
  openrouter.py               # OpenRouter rankings
analyzer.py                   # Delta computation, fast risers, new stars
backfill.py                   # One-time historical backfill from Wayback Machine
templates/index.html          # Single-page dashboard
data/                         # Cache files (gitignored)
```
