"""
Two things from OpenRouter:
  1. Pricing — /api/v1/models (free JSON API, per-token prices)
  2. Usage rank — /rankings page (RSC-encoded weekly token usage)
"""
import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup

CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "openrouter_cache.json")
CACHE_TTL = 7200

OR_MODELS_URL = "https://openrouter.ai/api/v1/models"
OR_RANKINGS_URL = "https://openrouter.ai/rankings"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    )
}


def _load_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    if time.time() - os.path.getmtime(CACHE_FILE) > CACHE_TTL:
        return None
    with open(CACHE_FILE) as f:
        return json.load(f)


def _save_cache(data):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)


def _fetch_pricing() -> dict[str, dict]:
    """Return {model_slug: {price_input, price_output}} from OR models API.
    Prices are per 1M tokens (API returns per-token strings).
    """
    try:
        r = requests.get(OR_MODELS_URL, timeout=15, headers=HEADERS)
        r.raise_for_status()
        models = r.json().get("data", [])
    except Exception:
        return {}

    result = {}
    for m in models:
        mid = m.get("id", "")  # e.g. "anthropic/claude-opus-4-6"
        if not mid:
            continue
        pricing = m.get("pricing", {})
        try:
            # API gives price per token as string; multiply by 1M
            price_in = float(pricing.get("prompt") or 0) * 1_000_000
            price_out = float(pricing.get("completion") or 0) * 1_000_000
        except (ValueError, TypeError):
            continue
        if price_in > 0 or price_out > 0:
            result[mid.lower()] = {
                "price_input": round(price_in, 4),
                "price_output": round(price_out, 4),
                "created": m.get("created"),
            }
    return result


def _fetch_usage_ranks() -> dict[str, dict[str, float]]:
    """Return {model_id: {"rank": rank, "tokens": tokens}} from latest week's token usage on OR rankings page."""
    try:
        r = requests.get(OR_RANKINGS_URL, timeout=20, headers=HEADERS)
        r.raise_for_status()
    except Exception:
        return {}

    text = r.text
    # Data is RSC-encoded: each quote is escaped as \"
    # Pattern: \"x\":\"YYYY-MM-DD\",\"ys\":{\"provider/model\":tokens,...}
    chunks = re.findall(
        r'\\"x\\":\\"([\d-]+)\\"[^}]*\\"ys\\":\{([^}]+)\}',
        text,
    )
    if not chunks:
        return {}

    latest_date = max(c[0] for c in chunks)
    ys_raw = next(ys for date, ys in chunks if date == latest_date)

    # Unescape \" → " then parse as JSON object
    clean = ys_raw.replace('\\"', '"')
    try:
        ys = json.loads("{" + clean + "}")
    except Exception:
        return {}

    # Sort by token volume desc, skip "Others"
    sorted_models = sorted(
        ((k, v) for k, v in ys.items() if k.lower() != "others"),
        key=lambda x: -x[1],
    )
    return {m.lower(): {"rank": rank, "tokens": tokens} for rank, (m, tokens) in enumerate(sorted_models, start=1)}


def fetch() -> dict:
    """Return merged {pricing: {...}, usage_ranks: {...}}."""
    cached = _load_cache()
    if cached is not None:
        return cached

    pricing = _fetch_pricing()
    usage_ranks = _fetch_usage_ranks()

    data = {"pricing": pricing, "usage_ranks": usage_ranks}
    _save_cache(data)
    return data
