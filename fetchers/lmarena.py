"""Fetch current LM Arena leaderboard data by scraping arena.ai."""
import json
import os
import re
import time
from typing import Optional
import requests
from bs4 import BeautifulSoup

CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "lmarena_cache.json")
SNAPSHOT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "lmarena_snapshot.json")
CACHE_TTL = 7200  # 2 hours

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
          "previous": {  # older snapshot for delta (may be None)
            "general": [...],
            "coding":  [...],
          },
          "fetched_at": unix_timestamp,
        }
    """
    cached = _load_cache()
    if cached is not None:
        return cached

    # Rotate: current → previous before fetching new
    previous = None
    if os.path.exists(SNAPSHOT_FILE):
        with open(SNAPSHOT_FILE) as f:
            previous = json.load(f)

    current = {}
    for cat, path in CATEGORIES.items():
        current[cat] = _scrape_category(path)

    now = time.time()
    data = {
        "current": current,
        "previous": previous,
        "fetched_at": now,
    }

    # Save new snapshot as the "previous" for next rotation
    os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump({"current": current, "fetched_at": now}, f)

    _save_cache(data)
    return data
