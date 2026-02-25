"""Fetch current LM Arena leaderboard data by scraping arena.ai."""
import json
import os
import re
import time
from typing import Optional
import requests
from bs4 import BeautifulSoup

_DIR = os.path.dirname(__file__)
CACHE_FILE        = os.path.join(_DIR, "..", "data", "lmarena_cache.json")
SNAPSHOT_7D_FILE  = os.path.join(_DIR, "..", "data", "lmarena_snapshot_7d.json")
SNAPSHOT_30D_FILE = os.path.join(_DIR, "..", "data", "lmarena_snapshot_30d.json")
SNAPSHOTS_DIR     = os.path.join(_DIR, "..", "data", "snapshots")

CACHE_TTL         = 7200        # 2 hours
SNAPSHOT_7D_TTL   = 7 * 86400  # 7 days
SNAPSHOT_30D_TTL  = 30 * 86400 # 30 days

BASE_URL = "https://arena.ai"
CATEGORIES = {
    "general": "/leaderboard/text",
    "coding": "/leaderboard/code",
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _load_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    age = time.time() - os.path.getmtime(CACHE_FILE)
    if age > CACHE_TTL:
        return None
    with open(CACHE_FILE) as f:
        return json.load(f)


def _save_cache(data):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)


def _load_snapshot(path: str) -> Optional[dict]:
    """Load snapshot and return its 'current' rankings dict, or None if missing."""
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            snap = json.load(f)
        return snap.get("current")
    except Exception:
        return None


def _get_closest_snapshot(target_seconds_ago: float) -> Optional[dict]:
    """Find the snapshot in snapshots/ closest to target_seconds_ago."""
    if not os.path.exists(SNAPSHOTS_DIR):
        return None
    
    now = time.time()
    target_ts = now - target_seconds_ago
    
    best_file = None
    best_diff = float('inf')
    
    for filename in os.listdir(SNAPSHOTS_DIR):
        if not filename.endswith(".json"):
            continue
        try:
            file_path = os.path.join(SNAPSHOTS_DIR, filename)
            # Use mtime as the proxy for when the snapshot was taken
            file_ts = os.path.getmtime(file_path)
            diff = abs(file_ts - target_ts)
            if diff < best_diff:
                best_diff = diff
                best_file = file_path
        except Exception:
            continue
            
    # Only return if it's reasonably close to the target (within 3 days)
    if best_file and best_diff < 3 * 86400:
         return _load_snapshot(best_file)
    return None


def _save_timestamped_snapshot(current: dict):
    """Save current data to a timestamped file in snapshots/."""
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    ts_str = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SNAPSHOTS_DIR, f"lmarena_{ts_str}.json")
    with open(path, "w") as f:
        json.dump({"current": current, "fetched_at": time.time()}, f)


def _rotate_snapshot(path: str, current: dict, now: float, ttl: int) -> None:
    """Write new snapshot if file is missing or older than ttl seconds."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    age = now - os.path.getmtime(path) if os.path.exists(path) else float("inf")
    if age >= ttl:
        with open(path, "w") as f:
            json.dump({"current": current, "fetched_at": now}, f)


def _parse_score(text: str) -> Optional[float]:
    """Extract numeric ELO from strings like '1504±8' or '1561+14/-14'."""
    m = re.match(r"([0-9]+)", text.strip())
    return float(m.group(1)) if m else None


def _scrape_category(path: str) -> list[dict]:
    """Return list of {rank, model_id, score, votes} for a category page."""
    url = BASE_URL + path
    resp = requests.get(url, timeout=20, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    rows = soup.select("tr")
    result = []
    for row in rows[1:]:  # skip header
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        # Rank is first cell
        try:
            rank = int(cells[0].get_text(strip=True))
        except ValueError:
            continue
        # Model ID from anchor title attribute (clean model ID)
        a = cells[2].find("a", title=True)
        model_id = a["title"] if a else cells[2].get_text(strip=True).split()[0]
        # Score (cells[3] on full pages which have Rank Spread; cells[2] on spotlight)
        score_text = cells[3].get_text(strip=True)
        score = _parse_score(score_text)
        # Votes
        try:
            votes = int(cells[4].get_text(strip=True).replace(",", ""))
        except (IndexError, ValueError):
            votes = 0

        if model_id and score is not None:
            result.append({
                "rank": rank,
                "model_id": model_id,
                "score": score,
                "votes": votes,
            })
    return result


def fetch() -> dict:
    """Return dict with current and previous snapshots for delta computation.

    Structure:
        {
          "current": {
            "general": [{rank, model_id, score, votes}, ...],
            "coding":  [{rank, model_id, score, votes}, ...],
          },
          "previous_7d":  {"general": [...], "coding": [...]},  # 7-day baseline
          "previous_30d": {"general": [...], "coding": [...]},  # 30-day baseline
          "fetched_at": unix_timestamp,
        }
    """
    cached = _load_cache()
    if cached is not None:
        return cached

    # Try high-res snapshots first, fall back to fixed snapshot files
    previous_7d = _get_closest_snapshot(7 * 86400) or _load_snapshot(SNAPSHOT_7D_FILE)
    previous_30d = _get_closest_snapshot(30 * 86400) or _load_snapshot(SNAPSHOT_30D_FILE)

    # Seed: if still missing and legacy exists, use legacy
    if not previous_7d or not previous_30d:
        legacy = os.path.join(_DIR, "..", "data", "lmarena_snapshot.json")
        if os.path.exists(legacy):
            leg_data = _load_snapshot(legacy)
            previous_7d = previous_7d or leg_data
            previous_30d = previous_30d or leg_data

    current = {}
    for cat, path in CATEGORIES.items():
        current[cat] = _scrape_category(path)

    now = time.time()
    data = {
        "current": current,
        "previous_7d": previous_7d,
        "previous_30d": previous_30d,
        "fetched_at": now,
    }

    # Save for future high-res baseline
    _save_timestamped_snapshot(current)

    # Maintain legacy fixed snapshots for compatibility/fallbacks
    _rotate_snapshot(SNAPSHOT_7D_FILE, current, now, SNAPSHOT_7D_TTL)
    _rotate_snapshot(SNAPSHOT_30D_FILE, current, now, SNAPSHOT_30D_TTL)

    _save_cache(data)
    return data
