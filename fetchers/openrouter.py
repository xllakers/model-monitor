"""Scrape OpenRouter /rankings for real-world usage rank."""
import json
import os
import time
import requests
from bs4 import BeautifulSoup

CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "openrouter_cache.json")
CACHE_TTL = 7200

OR_URL = "https://openrouter.ai/rankings"


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


def fetch() -> dict:
    """Return dict: { model_name_lower: rank (1-based int) }."""
    cached = _load_cache()
    if cached is not None:
        return cached

    result = {}
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(OR_URL, timeout=15, headers=headers)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # OpenRouter rankings page: look for model entries in a ranked list
        # The page is Next.js SSR — try extracting from __NEXT_DATA__ script
        script = soup.find("script", id="__NEXT_DATA__")
        if script and script.string:
            page_data = json.loads(script.string)
            # Navigate the nested props to find rankings list
            rankings = _extract_rankings_from_next_data(page_data)
            if rankings:
                result = rankings

        # Fallback: parse visible ranked rows
        if not result:
            rows = soup.select("tr, [data-rank]")
            rank = 1
            for row in rows:
                name_el = row.select_one("td:first-child, [data-model]")
                if name_el:
                    name = name_el.get_text(strip=True).lower()
                    if name:
                        result[name] = rank
                        rank += 1
    except Exception:
        pass

    _save_cache(result)
    return result


def _extract_rankings_from_next_data(data: dict) -> dict:
    """Recursively hunt for a list that looks like model rankings."""
    result = {}

    def _search(obj, depth=0):
        if depth > 10:
            return
        if isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, dict):
                    # Look for model identifier fields
                    name = (
                        item.get("slug")
                        or item.get("name")
                        or item.get("model_id")
                        or item.get("id")
                        or ""
                    )
                    if name and (item.get("rank") or i < 200):
                        rank = item.get("rank", i + 1)
                        result[str(name).lower()] = rank
                _search(item, depth + 1)
        elif isinstance(obj, dict):
            for v in obj.values():
                _search(v, depth + 1)

    _search(data)
    return result
