"""Compute fast risers, new stars, and merged signal rows from raw data."""
from __future__ import annotations
import re
from datetime import datetime
from typing import Optional


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _find_aa(model_id: str, aa: dict) -> dict:
    key = _norm(model_id)
    for k, v in aa.items():
        nk = _norm(k)
        if nk == key or nk in key or key in nk:
            return v
    return {}


def _find_or(model_id: str, or_ranks: dict) -> Optional[int]:
    key = _norm(model_id)
    for k, v in or_ranks.items():
        if _norm(k) in key or key in _norm(k):
            return v
    return None


def _model_display(model_id: str) -> str:
    return model_id.replace("-", " ").replace("_", " ").title()


def analyze(lmarena: dict, aa: dict, or_ranks: dict) -> dict:
    """
    lmarena shape:
      {
        "current":   {"general": [{rank, model_id, score, votes},...], "coding": [...]},
        "previous":  {"current": {"general": [{rank, model_id},...], "coding": [...]}} | None,
        "top50_30d": {"general": [model_id,...], "coding": [...]} | absent,
        "fetched_at": float,
      }
    """
    current = lmarena.get("current", {})
    prev_snap = lmarena.get("previous") or {}
    previous = prev_snap.get("current", {}) if isinstance(prev_snap, dict) else {}
    top50_30d = lmarena.get("top50_30d", {})

    fetched_at = lmarena.get("fetched_at", 0)
    last_updated = datetime.fromtimestamp(fetched_at).strftime("%Y-%m-%d %H:%M") if fetched_at else "N/A"

    rankings: dict[str, list] = {}
    fast_risers: dict[str, list] = {}
    new_stars: list = []

    for cat in ("general", "coding"):
        cur_rows = current.get(cat, [])
        prev_rows = previous.get(cat, [])

        # Previous ranks by model_id
        prev_rank_by_id = {r["model_id"]: r["rank"] for r in prev_rows}
        # 30d top-50 for new-star detection (prefer backfilled, fall back to prev)
        if top50_30d.get(cat):
            top50_set = set(top50_30d[cat])
        else:
            top50_set = {r["model_id"] for r in prev_rows if r["rank"] <= 50}

        merged = []
        for row in cur_rows:
            mid = row["model_id"]
            prev_rank = prev_rank_by_id.get(mid)
            # rank_delta: positive = moved up (lower rank number = better)
            rank_delta = (prev_rank - row["rank"]) if prev_rank is not None else None

            aa_info = _find_aa(mid, aa)
            or_rank = _find_or(mid, or_ranks)

            merged.append({
                "model_id": mid,
                "model_display": _model_display(mid),
                "rank": row["rank"],
                "elo": row.get("score", 0),
                "votes": row.get("votes", 0),
                "prev_rank": prev_rank,
                "rank_delta": rank_delta,    # positive = riser
                "price_input": aa_info.get("price_input"),
                "speed": aa_info.get("speed"),
                "or_rank": or_rank,
                "is_riser": False,
                "is_new_star": False,
            })

        rankings[cat] = merged

        # Fast risers: top 10 by rank improvement (only when prev data exists)
        risers = [r for r in merged if r["rank_delta"] is not None and r["rank_delta"] > 0]
        risers.sort(key=lambda x: -x["rank_delta"])
        top_risers = risers[:10]
        for r in top_risers:
            r["is_riser"] = True
        fast_risers[cat] = top_risers

        # New stars: in current top-30 but absent from 30d-ago top-50
        for r in merged:
            mid = r["model_id"]
            if r["rank"] <= 30 and mid not in top50_set and top50_set:
                r["is_new_star"] = True
                new_stars.append({**r, "category": cat})

    new_stars.sort(key=lambda x: x["rank"])

    return {
        "fast_risers": fast_risers,
        "new_stars": new_stars,
        "rankings": rankings,
        "last_updated": last_updated,
    }
