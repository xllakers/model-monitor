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


def prepare_summary(analysis_result: dict, company_momentum: list, model_picks: dict) -> str:
    lines = ["# LLM Arena Snapshot\n"]

    lines.append("## Fast Risers (top 5, 7d window)")
    for cat in ("general", "coding"):
        lines.append(f"### {cat.title()}")
        for r in analysis_result["fast_risers"]["7d"].get(cat, [])[:5]:
            lines.append(f"- {r['model_display']} ({r['lab']}) rank {r['rank']}, +{r['rank_delta']} positions, ELO {r['elo']}")

    lines.append("\n## New Stars (top 5, 7d window)")
    for r in analysis_result["new_stars"]["7d"][:5]:
        lines.append(f"- [{r['category']}] {r['model_display']} ({r['lab']}) rank {r['rank']}, ELO {r['elo']}")

    lines.append("\n## Company Momentum (top 8)")
    for entry in company_momentum[:8]:
        lines.append(
            f"- {entry['lab']}: score={entry['momentum_score']} "
            f"(risers={entry['fast_risers']}, new_stars={entry['new_stars']}, "
            f"top30_general={entry['top30_general']}, top30_coding={entry['top30_coding']}) "
            f"best_rank={entry['best_rank']} [{entry['top_model']}]"
        )

    lines.append("\n## Model Picks")
    pick_labels = [
        ("best_cloud", "Best Cloud"),
        ("best_oss", "Best OSS"),
        ("best_value_cloud", "Best Value Cloud"),
        ("best_value_oss", "Best Value OSS"),
        ("best_coding_cloud", "Best Coding Cloud"),
        ("best_coding_oss", "Best Coding OSS"),
    ]
    for key, label in pick_labels:
        m = model_picks.get(key)
        if m:
            price = f"${m['price_input']:.2f}/1M" if m.get("price_input") else "N/A"
            lines.append(f"- {label}: {m['model_display']} ({m['lab']}) ELO={m['elo']} price={price}")

    return "\n".join(lines)


def get_ai_insights(summary: str) -> str | None:
    prompt = (
        summary
        + "\n\n---\nProvide:\n"
        "1. Investment Watch: top companies by momentum + why\n"
        "2. Model Picks: best cloud/oss/value today\n"
        "3. Trends: notable patterns\n"
        "Be concise, bullets, actionable."
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
