"""
Backfill historical snapshots from Wayback Machine archived arena.ai/leaderboard pages.
Creates lmarena_snapshot.json with a 'previous' entry from ~7 days ago.

Run once: python3 backfill.py
"""
import json
import os
import re
import sys
import time
from typing import Optional
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from fetchers.lmarena import CACHE_FILE, SNAPSHOT_FILE, _scrape_category

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    )
}

# Category column indices in table 8 (0-based, after model col)
# Headers: Model | Overall | Expert | Hard Prompts | Coding | Math | Creative Writing | ...
CAT_COL = {"general": 1, "coding": 4}  # 1-based offset from cells[1:]


def _cdx_find_snapshot(target_ts: str) -> Optional[str]:
    """Find a 200-status snapshot URL closest to target_ts via CDX API."""
    url = (
        f"http://web.archive.org/cdx/search/cdx"
        f"?url=arena.ai/leaderboard&output=json&limit=5"
        f"&from={target_ts}&to={int(target_ts)+2000000}"
        f"&fl=timestamp,statuscode&filter=statuscode:200"
    )
    r = requests.get(url, timeout=15)
    rows = r.json()
    for row in rows[1:]:  # skip header
        if row[1] == "200":
            ts = row[0]
            return f"http://web.archive.org/web/{ts}/https://arena.ai/leaderboard"
    return None


def _parse_main_page(html: str) -> dict[str, list]:
    """Parse table 8 (full rank matrix) from main leaderboard page.
    Returns {"general": [{rank, model_id}], "coding": [...]}
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if len(tables) < 9:
        return {}

    t = tables[8]
    rows = t.find_all("tr")
    if not rows:
        return {}

    result: dict[str, list] = {"general": [], "coding": []}

    for row in rows[1:]:
        cells = row.find_all("td")
        if not cells:
            continue

        # Model ID: prefer span[title], fall back to stripping known org prefixes
        span = cells[0].find("span", title=True)
        if span and span.get("title"):
            model_id = span["title"].strip()
        else:
            raw = cells[0].get_text(strip=True)
            # strip leading org name (CamelCase prefix before first lowercase)
            import re
            m = re.match(r"^[A-Z][a-zA-Z]+([a-z][a-zA-Z0-9._-]+.*)", raw)
            model_id = m.group(1) if m else raw

        # Rank columns (cells[1] = Overall, cells[4] = Coding)
        for cat, col_idx in CAT_COL.items():
            if col_idx < len(cells):
                val = cells[col_idx].get_text(strip=True)
                try:
                    rank = int(val)
                    result[cat].append({"rank": rank, "model_id": model_id})
                except ValueError:
                    pass  # '-' means not ranked in this category

    # Sort by rank
    for cat in result:
        result[cat].sort(key=lambda x: x["rank"])

    return result


def fetch_historical(target_ts: str, label: str) -> Optional[dict]:
    """Fetch and parse a historical snapshot."""
    url = _cdx_find_snapshot(target_ts)
    if not url:
        print(f"  No snapshot found for {label}")
        return None
    print(f"  Fetching {label}: {url}")
    r = requests.get(url, timeout=30, headers=HEADERS)
    if r.status_code != 200:
        print(f"  HTTP {r.status_code}")
        return None
    parsed = _parse_main_page(r.text)
    if not parsed:
        print(f"  Parse failed")
        return None
    total = sum(len(v) for v in parsed.values())
    print(f"  Parsed: general={len(parsed['general'])}, coding={len(parsed['coding'])} models")
    return parsed


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Fetch current live data
    print("Fetching current live data...")
    current = {}
    for cat, path in [("general", "/leaderboard/text"), ("coding", "/leaderboard/code")]:
        rows = _scrape_category(path)
        current[cat] = rows
        print(f"  {cat}: {len(rows)} models, #1={rows[0]['model_id'] if rows else 'n/a'}")

    now = time.time()

    # Fetch ~7 days ago for 'previous' (used for fast risers delta)
    print("\nFetching ~7 days ago snapshot...")
    from datetime import datetime, timedelta
    ts_7d = (datetime.utcnow() - timedelta(days=7)).strftime("%Y%m%d%H%M%S")
    hist_7d = fetch_historical(ts_7d, "7d ago")

    # Fetch ~30 days ago for new-stars detection
    # If nothing found at 30d, walk back towards earliest available
    print("\nFetching ~30 days ago snapshot...")
    hist_30d = None
    for days_back in (30, 27, 25, 21):
        ts_30d = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y%m%d%H%M%S")
        hist_30d = fetch_historical(ts_30d, f"{days_back}d ago")
        if hist_30d:
            break

    # Build merged previous: use 30d for new-stars, 7d for deltas
    # The snapshot format that lmarena.fetch() wraps:
    # previous = {"current": {"general": [...], "coding": [...]}}
    # But historical data only has rank, not ELO score.
    # For delta: we'll add a placeholder score = 0 and let the rank delta drive fast-risers.
    # Actually, let's augment: fetch the spotlight tables (top-11) from the archived main page
    # to get actual ELO scores for top models, and fill rest with rank-only.

    # For simplicity: use 7d data as 'previous' with rank as proxy score
    # Fast risers = models whose rank improved most
    prev_data: dict[str, list] = {"general": [], "coding": []}

    if hist_7d:
        for cat in ("general", "coding"):
            for entry in hist_7d[cat]:
                # Invert rank to make it act like a score (lower rank = higher "score")
                # Use 1000 - rank as proxy ELO so delta = rank improvement
                prev_data[cat].append({
                    "rank": entry["rank"],
                    "model_id": entry["model_id"],
                    "score": 1000 - entry["rank"],
                    "votes": 0,
                })

    # For current data, also add proxy score based on rank for rank-delta computation
    # But we already have real ELO scores for current — keep those for display,
    # and add a proxy for delta vs historical rank.
    # Better: store both and let the analyzer handle it.

    # Save snapshot file: {current: {general: [...], coding: [...]}, fetched_at: ts}
    snapshot = {"current": current, "fetched_at": now}
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(snapshot, f)
    print(f"\nSaved current snapshot: {SNAPSHOT_FILE}")

    # Build and save the full cache that app.py uses
    # previous needs to have structure: {"current": {"general": [...], "coding": [...]}}
    previous_snap = {"current": prev_data, "fetched_at": now - 7 * 86400}

    # For new-stars: inject 30d top-50 info into previous as well
    # We'll add a special key "top50_30d" for the analyzer to use
    hist_30d_top50: dict[str, set] = {"general": set(), "coding": set()}
    if hist_30d:
        for cat in ("general", "coding"):
            hist_30d_top50[cat] = {e["model_id"] for e in hist_30d[cat] if e["rank"] <= 50}

    cache_data = {
        "current": current,
        "previous": previous_snap,
        "top50_30d": {k: list(v) for k, v in hist_30d_top50.items()},
        "fetched_at": now,
    }
    with open(CACHE_FILE, "w") as f:
        json.dump(cache_data, f)
    print(f"Saved cache with historical context: {CACHE_FILE}")

    # Preview
    print("\nPreview — 7d rank changes (general):")
    cur_ranks = {r["model_id"]: r["rank"] for r in current.get("general", [])}
    prev_ranks = {r["model_id"]: r["rank"] for r in prev_data.get("general", [])}
    deltas = []
    for mid, cur_r in cur_ranks.items():
        if mid in prev_ranks:
            delta = prev_ranks[mid] - cur_r  # positive = moved up
            deltas.append((mid, delta, cur_r, prev_ranks[mid]))
    deltas.sort(key=lambda x: -x[1])
    for mid, delta, cur_r, prev_r in deltas[:10]:
        if delta != 0:
            print(f"  {mid}: #{prev_r} → #{cur_r} ({'+' if delta>0 else ''}{delta})")


if __name__ == "__main__":
    main()
