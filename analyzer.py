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
                "context_length": price_info.get("context_length"),
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


def get_company_scorecard(analysis_result: dict, window: str = "7d") -> list:
    """Aggregate per-lab scorecard with market share, revenue proxy, portfolio depth."""
    labs: dict[str, dict] = {}

    # Compute total OR volume across unique models
    seen_vol: set[str] = set()
    total_volume = 0.0
    for cat in ("general", "coding"):
        for r in analysis_result["rankings"].get(cat, []):
            if r["model_id"] not in seen_vol:
                seen_vol.add(r["model_id"])
                total_volume += r.get("or_volume") or 0

    # Find category leaders (rank-1 model per category)
    leader_labs: set[str] = set()
    for cat in ("general", "coding"):
        rows = analysis_result["rankings"].get(cat, [])
        if rows:
            rank1 = min(rows, key=lambda r: r["rank"])
            leader_labs.add(rank1["lab"])

    def _get(lab: str, logo=None) -> dict:
        if lab not in labs:
            labs[lab] = {
                "lab": lab,
                "lab_logo": logo or logos.get_logo(lab),
                "top10_general": 0,
                "top10_coding": 0,
                "top30_general": 0,
                "top30_coding": 0,
                "fast_risers": 0,
                "new_stars": 0,
                "best_rank": None,
                "top_model": None,
                "oss_count": 0,
                "proprietary_count": 0,
                "market_volume": 0.0,
                "revenue_proxy": 0.0,
            }
        return labs[lab]

    seen_unique: set[str] = set()
    for cat in ("general", "coding"):
        for r in analysis_result["rankings"].get(cat, []):
            lab = r["lab"]
            entry = _get(lab, r.get("lab_logo"))
            if r["rank"] <= 10:
                entry[f"top10_{cat}"] += 1
            if r["rank"] <= 30:
                entry[f"top30_{cat}"] += 1
            if entry["best_rank"] is None or r["rank"] < entry["best_rank"]:
                entry["best_rank"] = r["rank"]
                entry["top_model"] = r["model_display"]
            # Volume/revenue counted once per model
            if r["model_id"] not in seen_unique:
                seen_unique.add(r["model_id"])
                vol = r.get("or_volume") or 0
                entry["market_volume"] += vol
                avg_price = ((r.get("price_input") or 0) + (r.get("price_output") or 0)) / 2
                entry["revenue_proxy"] += vol * avg_price / 1_000_000
                if r["is_open_source"]:
                    entry["oss_count"] += 1
                else:
                    entry["proprietary_count"] += 1

    fr_window = analysis_result["fast_risers"].get(window, {})
    for r in fr_window.get("general", []) + fr_window.get("coding", []):
        _get(r["lab"], r.get("lab_logo"))["fast_risers"] += 1

    for r in analysis_result["new_stars"].get(window, []):
        _get(r["lab"], r.get("lab_logo"))["new_stars"] += 1

    result = list(labs.values())
    for entry in result:
        entry["market_share_pct"] = (entry["market_volume"] / total_volume * 100) if total_volume > 0 else 0.0
        entry["category_leader"] = entry["lab"] in leader_labs
        momentum = entry["fast_risers"] * 3 + entry["new_stars"] * 5
        entry["momentum_score"] = momentum + entry["top30_general"] + entry["top30_coding"]
        top10 = entry["top10_general"] + entry["top10_coding"]
        entry["investment_score"] = round(
            momentum * 2
            + entry["market_share_pct"] * 1.5
            + (10 if entry["category_leader"] else 0)
            + top10 * 3,
            1,
        )

    result = [e for e in result if e["best_rank"] is not None]
    result.sort(key=lambda x: -x["investment_score"])
    return result


def get_company_momentum(analysis_result: dict, window: str = "7d") -> list:
    """Backward-compat alias for get_company_scorecard."""
    return get_company_scorecard(analysis_result, window)


def get_model_picks(analysis_result: dict) -> dict:
    """Return best cloud/OSS picks across 5 scenarios, each with a runner-up."""
    all_models: list[dict] = []
    seen: set[str] = set()
    for cat in ("general", "coding"):
        for r in analysis_result["rankings"].get(cat, []):
            if r["model_id"] not in seen:
                all_models.append(r)
                seen.add(r["model_id"])

    cloud = [m for m in all_models if not m["is_open_source"]]
    oss = [m for m in all_models if m["is_open_source"]]

    def best_by_elo(lst, exclude=None):
        valid = [m for m in lst if m.get("elo") and m["model_id"] != exclude]
        return max(valid, key=lambda x: x["elo"]) if valid else None

    def best_by_value(lst, exclude=None):
        valid = [m for m in lst if m.get("elo") and m.get("price_input") and m["model_id"] != exclude]
        if not valid:
            return None
        max_elo = max(m["elo"] for m in valid)
        min_elo = min(m["elo"] for m in valid)
        max_p = max(m["price_input"] for m in valid)
        min_p = min(m["price_input"] for m in valid)
        max_vol = max((m.get("or_volume") or 0) for m in valid)
        min_vol = min((m.get("or_volume") or 0) for m in valid)
        def _score(m):
            elo_norm = (m["elo"] - min_elo) / (max_elo - min_elo) if max_elo != min_elo else 1.0
            price_norm = (max_p - m["price_input"]) / (max_p - min_p) if max_p != min_p else 1.0
            vol_norm = ((m.get("or_volume") or 0) - min_vol) / (max_vol - min_vol) if max_vol != min_vol else 0.0
            return 0.5 * elo_norm + 0.3 * price_norm + 0.2 * vol_norm
        return max(valid, key=_score)

    def best_coding(lst, exclude=None):
        coding_models: list[dict] = []
        seen_coding: set[str] = set()
        for r in analysis_result["rankings"].get("coding", []):
            if r["model_id"] not in seen_coding:
                coding_models.append(r)
                seen_coding.add(r["model_id"])
        lst_ids = {x["model_id"] for x in lst}
        filtered = [m for m in coding_models if m["model_id"] in lst_ids and m["model_id"] != exclude]
        valid = [m for m in filtered if m.get("elo")]
        return max(valid, key=lambda x: x["elo"]) if valid else None

    def best_long_context(lst, min_ctx=128_000, exclude=None):
        valid = [m for m in lst if m.get("elo") and (m.get("context_length") or 0) >= min_ctx and m["model_id"] != exclude]
        return max(valid, key=lambda x: x["elo"]) if valid else None

    def most_adopted(lst, top_n=30, exclude=None):
        valid_elo = sorted([m for m in lst if m.get("elo")], key=lambda x: -x["elo"])
        top = valid_elo[:top_n]
        with_vol = [m for m in top if m.get("or_volume") and m["model_id"] != exclude]
        return max(with_vol, key=lambda x: x["or_volume"]) if with_vol else None

    picks: dict = {}

    bc = best_by_elo(cloud)
    picks["best_cloud"] = bc
    picks["best_cloud_ru"] = best_by_elo(cloud, exclude=bc["model_id"] if bc else None)

    bo = best_by_elo(oss)
    picks["best_oss"] = bo
    picks["best_oss_ru"] = best_by_elo(oss, exclude=bo["model_id"] if bo else None)

    bvc = best_by_value(cloud)
    picks["best_value_cloud"] = bvc
    picks["best_value_cloud_ru"] = best_by_value(cloud, exclude=bvc["model_id"] if bvc else None)

    bvo = best_by_value(oss)
    picks["best_value_oss"] = bvo
    picks["best_value_oss_ru"] = best_by_value(oss, exclude=bvo["model_id"] if bvo else None)

    bcc = best_coding(cloud)
    picks["best_coding_cloud"] = bcc
    picks["best_coding_cloud_ru"] = best_coding(cloud, exclude=bcc["model_id"] if bcc else None)

    bco = best_coding(oss)
    picks["best_coding_oss"] = bco
    picks["best_coding_oss_ru"] = best_coding(oss, exclude=bco["model_id"] if bco else None)

    blcc = best_long_context(cloud)
    picks["best_long_ctx_cloud"] = blcc
    picks["best_long_ctx_cloud_ru"] = best_long_context(cloud, exclude=blcc["model_id"] if blcc else None)

    blco = best_long_context(oss)
    picks["best_long_ctx_oss"] = blco
    picks["best_long_ctx_oss_ru"] = best_long_context(oss, exclude=blco["model_id"] if blco else None)

    mac = most_adopted(cloud)
    picks["most_adopted_cloud"] = mac
    picks["most_adopted_cloud_ru"] = most_adopted(cloud, exclude=mac["model_id"] if mac else None)

    mao = most_adopted(oss)
    picks["most_adopted_oss"] = mao
    picks["most_adopted_oss_ru"] = most_adopted(oss, exclude=mao["model_id"] if mao else None)

    return picks
