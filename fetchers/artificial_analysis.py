"""Fetch pricing/speed data from Artificial Analysis free API."""
import json
import os
import time
import requests

CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "aa_cache.json")
CACHE_TTL = 7200

AA_API_URL = "https://artificialanalysis.ai/api/models"


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
    """Return dict keyed by model slug: {price_input, speed, quality_index}."""
    cached = _load_cache()
    if cached is not None:
        return cached

    try:
        resp = requests.get(AA_API_URL, timeout=15, headers={"Accept": "application/json"})
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        # AA API may not be publicly accessible — return empty gracefully
        return {}

    result = {}
    models = raw if isinstance(raw, list) else raw.get("models", raw.get("data", []))
    for m in models:
        slug = m.get("model_id") or m.get("id") or m.get("slug") or ""
        if not slug:
            continue
        result[slug.lower()] = {
            "price_input": m.get("input_price") or m.get("price_per_million_input_tokens"),
            "speed": m.get("output_speed") or m.get("tokens_per_second") or m.get("speed"),
            "quality_index": m.get("quality_index") or m.get("elo"),
        }

    _save_cache(result)
    return result
