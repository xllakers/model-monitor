"""Flask entry point for LLM Monitor dashboard."""
from flask import Flask, render_template, request
from fetchers import lmarena, artificial_analysis, openrouter
from analyzer import analyze

app = Flask(__name__)


@app.route("/")
def index():
    page = request.args.get("page", 1, type=int)
    tab = request.args.get("tab", "general")
    sort_by = request.args.get("sort", "rank")
    sort_order = request.args.get("order", "asc")
    per_page = 50

    lm_data = lmarena.fetch()
    aa_data = artificial_analysis.fetch()
    or_data = openrouter.fetch()
    data = analyze(lm_data, aa_data, or_data)

    sort_map = {
        "rank": "rank",
        "elo": "elo",
        "delta": "rank_delta",
        "price": "price_input",
        "speed": "speed"
    }
    sort_key = sort_map.get(sort_by, "rank")
    reverse = (sort_order == "desc")

    def sort_list(items):
        # Handle None values by pushing them to the bottom
        items.sort(
            key=lambda x: (
                x.get(sort_key) is None, 
                x.get(sort_key) if x.get(sort_key) is not None else (float('-inf') if reverse else float('inf'))
            ),
            reverse=reverse
        )

    # Apply sorting to all sections
    for cat in data["rankings"]:
        sort_list(data["rankings"][cat])
    
    for cat in data["fast_risers"]:
        sort_list(data["fast_risers"][cat])
        
    sort_list(data["new_stars"])

    # Paginate rankings
    paginated_rankings = {}
    for cat, items in data["rankings"].items():
        total = len(items)
        start = (page - 1) * per_page
        end = start + per_page
        paginated_rankings[cat] = items[start:end]
        data[f"{cat}_total"] = total

    data["rankings"] = paginated_rankings
    data["page"] = page
    data["tab"] = tab
    data["sort_by"] = sort_by
    data["sort_order"] = sort_order
    data["per_page"] = per_page
    data["total_pages"] = (max(data["general_total"], data["coding_total"]) + per_page - 1) // per_page

    return render_template("index.html", **data)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
