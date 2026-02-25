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


def prepare_summary(analysis_result: dict) -> str:
    lines = ["# LLM Arena Snapshot\n"]

    lines.append("## Top Rankings (Top 15)")
    for cat in ("general", "coding"):
        lines.append(f"### {cat.title()}")
        for r in analysis_result["rankings"].get(cat, [])[:15]:
            or_str = f", OR vol {_fmt_vol(r.get('or_volume'))}" if r.get("or_volume") else ""
            price = f", ${r['price_input']:.2f}/1M" if r.get("price_input") else ""
            ctx = f", ctx {_fmt_ctx(r.get('context_length'))}" if r.get("context_length") else ""
            lines.append(f"- {r['model_display']} ({r['lab']}) rank {r['rank']}, ELO {r['elo']}{or_str}{price}{ctx}")

    lines.append("\n## Fast Risers (top 5, 7d window)")
    for cat in ("general", "coding"):
        lines.append(f"### {cat.title()}")
        for r in analysis_result["fast_risers"]["7d"].get(cat, [])[:5]:
            or_str = f", OR vol {_fmt_vol(r.get('or_volume'))}" if r.get("or_volume") else ""
            lines.append(f"- {r['model_display']} ({r['lab']}) rank {r['rank']}, +{r['rank_delta']} positions, ELO {r['elo']}{or_str}")

    lines.append("\n## New Stars (top 5, 7d window)")
    for r in analysis_result["new_stars"]["7d"][:5]:
        or_str = f", OR vol {_fmt_vol(r.get('or_volume'))}" if r.get("or_volume") else ""
        lines.append(f"- [{r['category']}] {r['model_display']} ({r['lab']}) rank {r['rank']}, ELO {r['elo']}{or_str}")

    return "\n".join(lines)


def get_ai_insights(summary: str) -> str | None:
    prompt = (
        summary
        + "\n\n---\n"
        "Data Legend: ELO (Quality), OR vol (Adoption/Usage), Price ($/1M tokens), Ctx (Context Window).\n\n"
        "Analyze the provided rankings, fast risers, and new stars to produce exactly 2 sections:\n\n"
        "## 1. Model Recommendations & Scenarios\n"
        "Based on the data, identify the best picks for:\n"
        "- The 'Daily Driver' (Top ELO + high adoption)\n"
        "- The 'Coding Powerhouse' (Best coding ELO)\n"
        "- The 'Value King' (Highest ELO-to-price ratio)\n"
        "- The 'Open Source Champion' (Best OSS model in top ranks)\n"
        "- The 'Hidden Gem' (High ELO but low OR volume)\n"
        "Explain each choice in 1 bullet point.\n\n"
        "## 2. Lab Momentum & Market Shifts\n"
        "Analyze which labs (Anthropic, OpenAI, Google, DeepSeek, etc.) are dominating the top 15 or surging in the risers. "
        "Identify 2-3 macro trends (e.g., price-performance shifts, proprietary vs. open-source gap, or specific lab surges).\n\n"
        "Be concise, technical, and actionable. No intro or outro fluff."
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
