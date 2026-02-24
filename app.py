"""Flask entry point for LLM Monitor dashboard."""
from flask import Flask, render_template
from fetchers import lmarena, artificial_analysis, openrouter
from analyzer import analyze

app = Flask(__name__)


@app.route("/")
def index():
    lm_data = lmarena.fetch()
    aa_data = artificial_analysis.fetch()
    or_data = openrouter.fetch()
    data = analyze(lm_data, aa_data, or_data)
    return render_template("index.html", **data)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
