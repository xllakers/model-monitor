"""Claude CLI integration for AI insights with 24hr cache."""
from __future__ import annotations
import json
import os
import subprocess
import time

_DIR = os.path.dirname(__file__)
CACHE_FILE = os.path.join(_DIR, "data", "ai_insights_cache.json")
CACHE_TTL = 43200  # 12 hours


def load_cached_insights() -> str | None:
    try:
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        if time.time() - cache.get("saved_at", 0) < CACHE_TTL:
            return cache.get("text")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def save_cached_insights(text: str) -> None:
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump({"saved_at": time.time(), "text": text}, f)


def _fmt_vol(v) -> str:
    if not v:
        return "N/A"
    if v >= 1_000_000_000:
        return f"{v/1_000_000_000:.1f}B"
    return f"{v/1_000_000:.1f}M"


def _fmt_ctx(c) -> str:
    if not c:
        return "N/A"
    if c >= 1_000_000:
        return f"{c//1_000_000}M"
    return f"{c//1_000}k"


def _fmt_rev(r) -> str:
    if not r:
        return "N/A"
    if r >= 1_000_000:
        return f"${r/1_000_000:.1f}M/wk"
    if r >= 1_000:
        return f"${r/1_000:.0f}K/wk"
    return f"${r:.0f}/wk"


def prepare_summary(analysis_result: dict, company_scorecard: list, model_picks: dict) -> str:
    lines = ["# LLM Arena Snapshot\n"]

    lines.append("## Fast Risers (top 5, 7d window)")
    for cat in ("general", "coding"):
        lines.append(f"### {cat.title()}")
        for r in analysis_result["fast_risers"]["7d"].get(cat, [])[:5]:
            or_str = f", OR vol {_fmt_vol(r.get('or_volume'))}" if r.get("or_volume") else ""
            lines.append(f"- {r['model_display']} ({r['lab']}) rank {r['rank']}, +{r['rank_delta']} positions, ELO {r['elo']}{or_str}")

    lines.append("\n## New Stars (top 5, 7d window)")
    for r in analysis_result["new_stars"]["7d"][:5]:
        or_str = f", OR vol {_fmt_vol(r.get('or_volume'))}" if r.get("or_volume") else ""
        lines.append(f"- [{r['category']}] {r['model_display']} ({r['lab']}) rank {r['rank']}, ELO {r['elo']}{or_str}")

    lines.append("\n## Company Scorecard (top 8)")
    for entry in company_scorecard[:8]:
        mkt = f"{entry.get('market_share_pct', 0):.1f}%"
        rev = _fmt_rev(entry.get("revenue_proxy"))
        top10 = f"{entry.get('top10_general', 0)}G/{entry.get('top10_coding', 0)}C"
        top30 = f"{entry.get('top30_general', 0)}G/{entry.get('top30_coding', 0)}C"
        oss_prop = f"{entry.get('oss_count', 0)} OSS / {entry.get('proprietary_count', 0)} prop"
        leader = " [CATEGORY LEADER]" if entry.get("category_leader") else ""
        lines.append(
            f"- {entry['lab']}: invest_score={entry.get('investment_score', 0)} "
            f"mkt_share={mkt} rev={rev} top10={top10} top30={top30} "
            f"portfolio={oss_prop} momentum={entry.get('momentum_score', 0)}"
            f" best_rank={entry['best_rank']} [{entry['top_model']}]{leader}"
        )

    lines.append("\n## Model Picks")
    pick_labels = [
        ("best_cloud",        "Best Overall Cloud"),
        ("best_oss",          "Best Overall OSS"),
        ("best_value_cloud",  "Best Value Cloud"),
        ("best_value_oss",    "Best Value OSS"),
        ("best_coding_cloud", "Best Coding Cloud"),
        ("best_coding_oss",   "Best Coding OSS"),
        ("best_long_ctx_cloud", "Best Long Context Cloud"),
        ("best_long_ctx_oss",   "Best Long Context OSS"),
        ("most_adopted_cloud",  "Most Adopted Cloud"),
        ("most_adopted_oss",    "Most Adopted OSS"),
    ]
    for key, label in pick_labels:
        m = model_picks.get(key)
        ru = model_picks.get(key + "_ru")
        if m:
            price = f"${m['price_input']:.2f}/1M" if m.get("price_input") else "N/A"
            ctx = _fmt_ctx(m.get("context_length"))
            vol = _fmt_vol(m.get("or_volume"))
            ru_str = f" (runner-up: {ru['model_display']})" if ru else ""
            lines.append(f"- {label}: {m['model_display']} ({m['lab']}) ELO={m['elo']} price={price} ctx={ctx} vol={vol}{ru_str}")

    return "\n".join(lines)


def get_ai_insights(summary: str) -> str | None:
    prompt = (
        summary
        + "\n\n---\n"
        "Data: Arena ELO (quality), OpenRouter (OR) volume (real-world adoption), "
        "market share (% of OR tokens), revenue proxy (volume × price), context_length.\n\n"
        "Provide exactly 3 sections:\n\n"
        "## 1. Model Recommendations\n"
        "For each scenario below, name the pick and explain in 1 sentence why:\n"
        "- Daily driver (best all-round)\n"
        "- Coding specialist\n"
        "- Budget / high-value\n"
        "- Self-hosted / open-source\n"
        "- Long-context tasks\n"
        "Flag any 'hidden gems': high ELO but low OR adoption (underutilized).\n\n"
        "## 2. Investment Watch\n"
        "Top 4 companies. For each: market position, revenue signal, portfolio strength, momentum, key risk. Bullets.\n\n"
        "## 3. Key Trends\n"
        "2-3 macro patterns visible in the data (e.g. OSS closing gap, price compression, specific lab surge).\n\n"
        "Be concise, bullets, actionable. No intro fluff."
    )
    import os
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        elif result.returncode != 0:
            print(f"AI insights failed: {result.stderr or 'unknown error'}")
    except subprocess.TimeoutExpired:
        print("AI insights skipped: timeout")
    except FileNotFoundError:
        print("AI insights skipped: claude CLI not found")
    return None
