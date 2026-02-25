"""Compute fast risers, new stars, and merged signal rows from raw data."""
from __future__ import annotations
import re
import time
from datetime import datetime
from typing import Optional
import logos

def get_lab_from_model_id(model_id: str) -> str:
    mid = model_id.split("/", 1)[-1].lower()
    RULES = [
        ("claude", "Anthropic"), ("gpt", "OpenAI"), ("o1", "OpenAI"), ("o3", "OpenAI"),
        ("chatgpt", "OpenAI"), ("gemini", "Google"), ("gemma", "Google"), ("grok", "xAI"), ("dola", "ByteDance"),
        ("llama-3.1-nemotron", "NVIDIA"), ("llama-3.3-nemotron", "NVIDIA"),
        ("nemotron", "NVIDIA"), ("llama", "Meta"), ("mistral", "Mistral"),
        ("mixtral", "Mistral"), ("ministral", "Mistral"), ("deepseek", "DeepSeek"),
        ("qwen", "Alibaba"), ("qwq", "Alibaba"), ("phi", "Microsoft"),
        ("command", "Cohere"), ("kimi", "Moonshot"), ("glm", "Zhipu"),
        ("granite", "IBM"), ("olmo", "AI2"), ("molmo", "AI2"),
        ("jamba", "AI21 Labs"), ("yi", "01.AI"),
        ("minimax", "MiniMax"), ("abab", "MiniMax"),
        ("ernie", "Baidu"),
    ]
    for prefix, lab in RULES:
        if mid.startswith(prefix):
            return lab
    return "Unknown"


def get_is_open_source(model_id: str) -> bool:
    mid = model_id.split("/", 1)[-1].lower()
    OPEN = ["llama", "gemma", "mistral", "mixtral", "ministral", "deepseek",
            "qwen", "qwq", "phi", "command-r", "granite", "olmo", "molmo",
            "jamba", "llama-3.1-nemotron", "llama-3.3-nemotron"]
    return any(mid.startswith(p) for p in OPEN)


def _norm(s: str) -> str:
    """Strip provider prefix, remove non-alphanumeric, lowercase."""
    s = s.split("/", 1)[-1]
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _tokens(s: str) -> set:
    """Token set for fuzzy matching: strip provider, date suffixes, split on separators."""
    s = s.split("/", 1)[-1]                          # strip "provider/"
    s = re.sub(r"-\d{8}$", "", s)                   # strip trailing -YYYYMMDD
    s = re.sub(r":\w+$", "", s)                      # strip :free, :nitro etc.
    parts = re.split(r"[^a-z0-9]+", s.lower())
    return {p for p in parts if p}


def _token_overlap(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _find_pricing(model_id: str, pricing: dict) -> dict:
    """Match lmarena model_id to OR pricing dict (keyed by 'provider/slug')."""
    key = _norm(model_id)
    ktok = _tokens(model_id)
    best, best_score = {}, 0.0
    for or_id, v in pricing.items():
        nk = _norm(or_id)
        if nk == key:
            return v
        score = _token_overlap(ktok, _tokens(or_id))
        if score > best_score:
            best, best_score = v, score
    return best if best_score >= 0.5 else {}


def _find_usage_info(model_id: str, usage_ranks: dict) -> Optional[dict]:
    """Match lmarena model_id to OR usage info (keyed by 'provider/slug')."""
    key = _norm(model_id)
    ktok = _tokens(model_id)
    best, best_score = None, 0.0
    for or_id, info in usage_ranks.items():
        nk = _norm(or_id)
        if nk == key:
            return info
        score = _token_overlap(ktok, _tokens(or_id))
        if score > best_score:
            best, best_score = info, score
    return best if best_score >= 0.5 else None


def _model_display(model_id: str) -> str:
    return model_id.replace("-", " ").replace("_", " ").title()


def analyze(lmarena: dict, aa: dict, or_data: dict) -> dict:
    """
    lmarena shape:
      {
        "current":     {"general": [{rank, model_id, score, votes},...], "coding": [...]},
        "previous_7d":  {"general": [...], "coding": [...]},  # 7-day baseline
        "previous_30d": {"general": [...], "coding": [...]},  # 30-day baseline
        "fetched_at": float,
      }
    or_data shape (from openrouter.fetch()):
      {
        "pricing":     {"provider/slug": {price_input, price_output}},
        "usage_ranks": {"provider/slug": rank_int},
      }
    """
    pricing = or_data.get("pricing", {})
    usage_ranks = or_data.get("usage_ranks", {})
    current = lmarena.get("current", {})
    previous_7d = lmarena.get("previous_7d") or {}
    previous_30d = lmarena.get("previous_30d") or {}

    fetched_at = lmarena.get("fetched_at", 0)
    last_updated = datetime.fromtimestamp(fetched_at).strftime("%Y-%m-%d %H:%M") if fetched_at else "N/A"

    rankings: dict[str, list] = {}
    fast_risers: dict[str, dict[str, list]] = {"7d": {}, "30d": {}}
    new_stars: dict[str, list] = {"7d": [], "30d": []}

    for cat in ("general", "coding"):
        cur_rows = current.get(cat, [])

        # Previous rank maps for each window
        prev_7d_by_id  = {r["model_id"]: r["rank"] for r in previous_7d.get(cat, [])}
        prev_30d_by_id = {r["model_id"]: r["rank"] for r in previous_30d.get(cat, [])}

        merged = []
        for row in cur_rows:
            mid = row["model_id"]
            prev_rank_7d = prev_7d_by_id.get(mid)
            # Leaderboard rank_delta uses 7d window (most actionable)
            rank_delta = (prev_rank_7d - row["rank"]) if prev_rank_7d is not None else None

            price_info = _find_pricing(mid, pricing)
            _ui = _find_usage_info(mid, usage_ranks)
            usage_info = _ui if isinstance(_ui, dict) else {}
            or_rank = usage_info.get("rank")
            or_volume = usage_info.get("tokens")
            
            created_ts = price_info.get("created")
            days_in_board = int((time.time() - created_ts) / 86400) if created_ts else None

            merged.append({
                "model_id": mid,
                "model_display": _model_display(mid),
                "rank": row["rank"],
                "elo": row.get("score", 0),
                "votes": row.get("votes", 0),
                "prev_rank": prev_rank_7d,
                "rank_delta": rank_delta,    # positive = riser (7d)
                "price_input": price_info.get("price_input"),
                "price_output": price_info.get("price_output"),
                "days_in_board": days_in_board,
                "or_rank": or_rank,
                "or_volume": or_volume,
                "is_riser": False,
                "is_new_star": False,
                "lab": get_lab_from_model_id(mid),
                "lab_logo": logos.get_logo(get_lab_from_model_id(mid)),
                "is_open_source": get_is_open_source(mid),
            })

        rankings[cat] = merged

        # Compute fast risers and new stars for both windows
        for window, prev_by_id, prev_rows_w in [
            ("7d",  prev_7d_by_id,  previous_7d),
            ("30d", prev_30d_by_id, previous_30d),
        ]:
            risers = [
                {**r, "rank_delta": prev_by_id[r["model_id"]] - r["rank"]}
                for r in merged
                if r["model_id"] in prev_by_id
                and prev_by_id[r["model_id"]] - r["rank"] > 0
            ]
            risers.sort(key=lambda x: -x["rank_delta"])
            fast_risers[window][cat] = risers[:10]

            top50 = {r["model_id"] for r in prev_rows_w.get(cat, []) if r["rank"] <= 50}
            for r in merged:
                if r["rank"] <= 30 and r["model_id"] not in top50 and top50:
                    if window == "7d":
                        r["is_new_star"] = True
                    new_stars[window].append({**r, "category": cat})

        # Mark is_riser on merged rows from 7d window
        riser_ids_7d = {r["model_id"] for r in fast_risers["7d"].get(cat, [])}
        for r in merged:
            if r["model_id"] in riser_ids_7d:
                r["is_riser"] = True

    for window in new_stars:
        new_stars[window].sort(key=lambda x: x["rank"])

    return {
        "fast_risers": fast_risers,
        "new_stars": new_stars,
        "rankings": rankings,
        "last_updated": last_updated,
    }


def get_company_momentum(analysis_result: dict, window: str = "7d") -> list:
    """Aggregate per-lab momentum from full (pre-pagination) rankings."""
    labs: dict[str, dict] = {}

    def _get(lab: str) -> dict:
        if lab not in labs:
            labs[lab] = {
                "lab": lab,
                "lab_logo": logos.get_logo(lab),
                "top30_general": 0,
                "top30_coding": 0,
                "fast_risers": 0,
                "new_stars": 0,
                "best_rank": None,
                "top_model": None,
            }
        return labs[lab]

    for cat in ("general", "coding"):
        for r in analysis_result["rankings"].get(cat, []):
            lab = r["lab"]
            entry = _get(lab)
            if r["rank"] <= 30:
                entry[f"top30_{cat}"] += 1
            # Track best rank overall
            if entry["best_rank"] is None or r["rank"] < entry["best_rank"]:
                entry["best_rank"] = r["rank"]
                entry["top_model"] = r["model_display"]

    fr_window = analysis_result["fast_risers"].get(window, {})
    for r in fr_window.get("general", []) + fr_window.get("coding", []):
        _get(r["lab"])["fast_risers"] += 1

    for r in analysis_result["new_stars"].get(window, []):
        _get(r["lab"])["new_stars"] += 1

    result = list(labs.values())
    for entry in result:
        entry["momentum_score"] = (
            entry["fast_risers"] * 3
            + entry["new_stars"] * 5
            + entry["top30_general"]
            + entry["top30_coding"]
        )

    result.sort(key=lambda x: -x["momentum_score"])
    return [e for e in result if e["momentum_score"] > 0]


def get_model_picks(analysis_result: dict) -> dict:
    """Return best cloud/OSS picks by ELO and value (ELO/price)."""
    all_models: list[dict] = []
    seen: set[str] = set()
    # Merge general + coding, deduplicate by model_id (prefer general rank)
    for cat in ("general", "coding"):
        for r in analysis_result["rankings"].get(cat, []):
            if r["model_id"] not in seen:
                all_models.append(r)
                seen.add(r["model_id"])

    cloud = [m for m in all_models if not m["is_open_source"]]
    oss = [m for m in all_models if m["is_open_source"]]

    def best_by_elo(lst):
        valid = [m for m in lst if m.get("elo")]
        return max(valid, key=lambda x: x["elo"]) if valid else None

    def best_by_value(lst):
        valid = [m for m in lst if m.get("elo") and m.get("price_input")]
        if not valid:
            return None
        max_elo = max(m["elo"] for m in valid)
        min_elo = min(m["elo"] for m in valid)
        max_p = max(m["price_input"] for m in valid)
        min_p = min(m["price_input"] for m in valid)
        def _score(m):
            elo_norm = (m["elo"] - min_elo) / (max_elo - min_elo) if max_elo != min_elo else 1.0
            price_norm = (max_p - m["price_input"]) / (max_p - min_p) if max_p != min_p else 1.0
            return 0.6 * elo_norm + 0.4 * price_norm
        return max(valid, key=_score)

    def best_coding(lst):
        coding_models: list[dict] = []
        seen_coding: set[str] = set()
        for r in analysis_result["rankings"].get("coding", []):
            if r["model_id"] not in seen_coding:
                coding_models.append(r)
                seen_coding.add(r["model_id"])
        filtered = [m for m in coding_models if m["model_id"] in {x["model_id"] for x in lst}]
        valid = [m for m in filtered if m.get("elo")]
        return max(valid, key=lambda x: x["elo"]) if valid else None

    return {
        "best_cloud": best_by_elo(cloud),
        "best_oss": best_by_elo(oss),
        "best_value_cloud": best_by_value(cloud),
        "best_value_oss": best_by_value(oss),
        "best_coding_cloud": best_coding(cloud),
        "best_coding_oss": best_coding(oss),
    }
