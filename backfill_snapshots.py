#!/usr/bin/env python3
"""Backfill 7d and 30d snapshot baselines from Wayback Machine archives.

Usage:
    python3 backfill_snapshots.py

Queries archive.org for the closest available snapshots to 7 and 30 days ago,
parses them with the same logic as the live scraper, and writes snapshot files.
Run once after setup, then delete the lmarena cache so deltas take effect.
"""
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ── paths ────────────────────────────────────────────────────────────────────
_DIR = os.path.dirname(__file__)
SNAPSHOT_7D_FILE  = os.path.join(_DIR, "data", "lmarena_snapshot_7d.json")
SNAPSHOT_30D_FILE = os.path.join(_DIR, "data", "lmarena_snapshot_30d.json")

# ── constants ─────────────────────────────────────────────────────────────────
BASE_URL     = "https://arena.ai"
WAYBACK_BASE = "https://web.archive.org/web"
WAYBACK_CDX  = "https://web.archive.org/cdx/search/cdx"
CATEGORIES   = {"general": "/leaderboard/text", "coding": "/leaderboard/code"}
HEADERS      = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
# Accept snapshots within this many days of the target
MAX_DRIFT_DAYS = 7


def _parse_score(text: str) -> Optional[float]:
    m = re.match(r"([0-9]+)", text.strip())
    return float(m.group(1)) if m else None


def _parse_leaderboard_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    result = []
    for row in soup.select("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        try:
            rank = int(cells[0].get_text(strip=True))
        except ValueError:
            continue
        a = cells[2].find("a", title=True)
        model_id = a["title"] if a else cells[2].get_text(strip=True).split()[0]
        score = _parse_score(cells[3].get_text(strip=True))
        try:
            votes = int(cells[4].get_text(strip=True).replace(",", ""))
        except (IndexError, ValueError):
            votes = 0
        if model_id and score is not None:
            result.append({"rank": rank, "model_id": model_id,
                           "score": score, "votes": votes})
    return result


def find_closest_snapshot(url: str, target: datetime) -> Optional[tuple[str, datetime]]:
    """Return (wayback_url, actual_datetime) for the closest 200 snapshot."""
    ts = target.strftime("%Y%m%d%H%M%S")
    # Search a ±MAX_DRIFT_DAYS window around target
    frm = (target - timedelta(days=MAX_DRIFT_DAYS)).strftime("%Y%m%d000000")
    to  = (target + timedelta(days=1)).strftime("%Y%m%d235959")
    params = {
        "url":    url,
        "output": "json",
        "from":   frm,
        "to":     to,
        "fl":     "timestamp",
        "filter": "statuscode:200",
        "limit":  50,
    }
    try:
        resp = requests.get(WAYBACK_CDX, params=params, timeout=15)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:
        print(f"    CDX error: {e}")
        return None

    if len(rows) < 2:   # rows[0] is header
        return None

    # Pick timestamp closest to target
    best_ts, best_dt, best_delta = None, None, float("inf")
    for row in rows[1:]:
        ts_str = row[0]
        dt = datetime.strptime(ts_str, "%Y%m%d%H%M%S")
        delta = abs((dt - target).total_seconds())
        if delta < best_delta:
            best_ts, best_dt, best_delta = ts_str, dt, delta

    if best_ts is None:
        return None

    wayback_url = f"{WAYBACK_BASE}/{best_ts}/{url}"
    return wayback_url, best_dt


def fetch_and_parse(wayback_url: str) -> list[dict]:
    resp = requests.get(wayback_url, timeout=40, headers=HEADERS)
    resp.raise_for_status()
    return _parse_leaderboard_html(resp.text)


# Known-good Wayback timestamps discovered via CDX (2026-02-25).
# Format: { cat: (wayback_timestamp, actual_date_approx) }
KNOWN_SNAPSHOTS = {
    "7d": {
        # target 2026-02-18 (7 days ago)
        "general": ("20260218122329", "2026-02-18"),
        "coding":  ("20260217152450", "2026-02-17"),
    },
    "30d": {
        # target 2026-01-26 (30 days ago); earliest archived is Jan 31
        "general": ("20260131090431", "2026-01-31"),
        "coding":  ("20260202161428", "2026-02-02"),
    },
}


def backfill_window(label: str, target: datetime, out_file: str) -> bool:
    print(f"\n{'─'*56}")
    print(f"  {label}  (target: {target.strftime('%Y-%m-%d')})")
    print(f"{'─'*56}")

    cats: dict[str, list] = {}
    fetched_timestamps: list[float] = []
    known = KNOWN_SNAPSHOTS.get(label, {})

    for cat, path in CATEGORIES.items():
        url = BASE_URL + path

        # Try CDX first (dynamic), fall back to known hardcoded timestamps
        result = None
        print(f"\n  [{cat}] Finding snapshot near {target.strftime('%Y-%m-%d')}…")
        try:
            result = find_closest_snapshot(url, target)
        except Exception:
            pass

        if result is None and cat in known:
            ts_str, date_str = known[cat]
            actual_dt = datetime.strptime(ts_str, "%Y%m%d%H%M%S")
            wayback_url = f"{WAYBACK_BASE}/{ts_str}/{url}"
            print(f"    CDX unavailable — using known snapshot: {date_str}")
            result = (wayback_url, actual_dt)

        if result is None:
            print(f"    No snapshot found — skipping.")
            cats[cat] = []
            continue

        wayback_url, actual_dt = result
        drift = round((actual_dt - target).total_seconds() / 86400, 1)
        drift_str = f"+{drift}d" if drift >= 0 else f"{drift}d"
        print(f"    Snapshot: {actual_dt.strftime('%Y-%m-%d %H:%M')} ({drift_str} from target)")
        print(f"    Fetching…")

        try:
            rows = fetch_and_parse(wayback_url)
        except Exception as e:
            print(f"    Failed: {e}")
            cats[cat] = []
            continue

        top3 = ", ".join(f"#{r['rank']} {r['model_id']}" for r in rows[:3])
        print(f"    Parsed {len(rows)} models — top3: {top3}")
        cats[cat] = rows
        fetched_timestamps.append(actual_dt.timestamp())
        time.sleep(2)   # polite to archive.org

    total = sum(len(v) for v in cats.values())
    if total == 0:
        print(f"\n  ✗ No data retrieved for {label} — file not written.")
        return False

    snap_ts = min(fetched_timestamps) if fetched_timestamps else target.timestamp()
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w") as f:
        json.dump({"current": cats, "fetched_at": snap_ts}, f)
    print(f"\n  ✓ Saved {total} rows → {out_file}")
    return True


def main():
    now = datetime.now()
    targets = [
        ("7d",  now - timedelta(days=7),  SNAPSHOT_7D_FILE),
        ("30d", now - timedelta(days=30), SNAPSHOT_30D_FILE),
    ]

    results = []
    for label, target, out_file in targets:
        ok = backfill_window(label, target, out_file)
        results.append((label, ok))

    print(f"\n{'═'*56}")
    print("  Summary")
    print(f"{'═'*56}")
    any_ok = False
    for label, ok in results:
        status = "✓ OK" if ok else "✗ No archive available"
        print(f"  {label:4s}  {status}")
        any_ok = any_ok or ok

    if any_ok:
        cache = os.path.join(_DIR, "data", "lmarena_cache.json")
        if os.path.exists(cache):
            os.remove(cache)
            print(f"\n  Cleared {cache} — next page load will use new baselines.")
        else:
            print(f"\n  (Cache already absent — you're good to go.)")

    print()


if __name__ == "__main__":
    main()
