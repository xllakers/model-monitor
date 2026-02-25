"""Flask entry point for LLM Monitor dashboard."""
from flask import Flask, render_template, request, jsonify
from fetchers import lmarena, artificial_analysis, openrouter
from analyzer import analyze
from ai_analysis import load_cached_insights, save_cached_insights, prepare_summary, get_ai_insights

app = Flask(__name__)


@app.route("/")
def index():
    page = request.args.get("page", 1, type=int)
    tab = request.args.get("tab", "general")
    sort_lb_by = request.args.get("sort_lb", "rank")
    sort_lb_order = request.args.get("order_lb", "asc")
    sort_fr_by = request.args.get("sort_fr", "delta")
    sort_fr_order = request.args.get("order_fr", "desc")
    sort_ns_by = request.args.get("sort_ns", "rank")
    sort_ns_order = request.args.get("order_ns", "asc")
    per_page = 25

    lm_data = lmarena.fetch()
    aa_data = artificial_analysis.fetch()
    or_data = openrouter.fetch()
    data = analyze(lm_data, aa_data, or_data)

    sort_map = {
        "rank": "rank",
        "elo": "elo",
        "delta": "rank_delta",
        "price": "price_input",
        "days_in_board": "days_in_board",
        "volume": "or_volume"
    }

    def sort_list(items, sort_by, sort_order):
        sort_key = sort_map.get(sort_by, "rank")
        reverse = (sort_order == "desc")
        
        items.sort(
            key=lambda x: x.get(sort_key) if x.get(sort_key) is not None else (-float('inf') if reverse else float('inf')),
            reverse=reverse
        )

    # Apply sorting to all sections independently
    for cat in data["rankings"]:
        sort_list(data["rankings"][cat], sort_lb_by, sort_lb_order)
    
    for window in ("7d", "30d"):
        for cat in data["fast_risers"].get(window, {}):
            sort_list(data["fast_risers"][window][cat], sort_fr_by, sort_fr_order)

    for window in ("7d", "30d"):
        for cat in data["new_stars"].get(window, {}):
            sort_list(data["new_stars"][window][cat], sort_ns_by, sort_ns_order)

    # Paginate rankings
    paginated_rankings = {}
    for cat, items in data["rankings"].items():
        total = len(items)
        start = (page - 1) * per_page
        end = start + per_page
        paginated_rankings[cat] = items[start:end]
        data[f"{cat}_total"] = total

    data["rankings"] = paginated_rankings
    data["ai_insights"] = load_cached_insights()
    data["page"] = page
    data["tab"] = tab
    data["sort_lb_by"] = sort_lb_by
    data["sort_lb_order"] = sort_lb_order
    data["sort_fr_by"] = sort_fr_by
    data["sort_fr_order"] = sort_fr_order
    data["sort_ns_by"] = sort_ns_by
    data["sort_ns_order"] = sort_ns_order
    data["per_page"] = per_page
    data["total_pages"] = (max(data["general_total"], data["coding_total"]) + per_page - 1) // per_page

    return render_template("index.html", **data)


@app.route("/ai-insights", methods=["POST"])
def ai_insights_endpoint():
    lm_data = lmarena.fetch()
    aa_data = artificial_analysis.fetch()
    or_data = openrouter.fetch()
    data = analyze(lm_data, aa_data, or_data)
    summary = prepare_summary(data)
    text = get_ai_insights(summary)
    if text:
        save_cached_insights(text)
        return jsonify({"status": "ok", "text": text})
    return jsonify({"status": "error", "text": "Claude CLI unavailable"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
