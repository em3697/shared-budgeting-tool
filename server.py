"""
Local dashboard server.

Serves the same dashboard UI build_dashboard.py generates statically, but
live: a "Refresh" button re-fetches current numbers from the Sheet, and
category/Shared edits are POSTed straight to this process and applied
immediately — no more download-a-JSON-file-then-run-a-script round trip.

Runs on localhost only. The service-account credential lives in this
process exactly like it does in every other script here — it never reaches
the browser.

Usage:
    python server.py
"""

import json
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request

import config
import sheets_client
from apply_category_edits import apply_edits
from build_dashboard import compute_dashboard_data, record_history_snapshot
from categorize import load_categories

HOST = "127.0.0.1"
PORT = 5151  # not 5000 — collides with macOS AirPlay Receiver

TEMPLATE_FILE = Path(__file__).parent / "dashboard_template.html"

GENERATED_NOTE = "Generated locally by build_dashboard.py — re-run it any time after a new import."
SERVED_NOTE = "Served locally by server.py — click Refresh for the latest numbers."

app = Flask(__name__)


def _load_cfg_and_sheet():
    sheet = sheets_client.get_spreadsheet()
    mapping_rows = sheets_client.read_all_rows(sheet, config.CATEGORY_MAPPINGS_TAB)
    budget_rows = sheets_client.read_all_rows(sheet, config.CATEGORIES_TAB)
    cfg = load_categories(mapping_rows, budget_rows)
    return sheet, cfg


def _snapshot_best_effort(data: dict) -> None:
    # History recording is a side effect on top of the dashboard's core job
    # of showing current numbers — a failure here (rate limit, transient API
    # error) should never take down page load or refresh.
    try:
        record_history_snapshot(data)
    except Exception as e:
        print(f"WARNING: could not record history snapshot: {e}")


@app.route("/")
def index():
    if not TEMPLATE_FILE.exists():
        return "dashboard_template.html not found", 500
    try:
        data = compute_dashboard_data()
    except Exception as e:
        return f"Could not load data from the Sheet: {e}", 502
    _snapshot_best_effort(data)

    embedded_json = json.dumps(data).replace("</", "<\\/")
    template = TEMPLATE_FILE.read_text()
    rendered = template.replace("__DASHBOARD_DATA__", embedded_json).replace(GENERATED_NOTE, SERVED_NOTE)
    return rendered


@app.route("/api/data")
def api_data():
    try:
        data = compute_dashboard_data()
    except Exception as e:
        return jsonify({"error": f"Could not load data from the Sheet: {e}"}), 502
    _snapshot_best_effort(data)
    return jsonify(data)


@app.route("/api/edits", methods=["POST"])
def api_edits():
    body = request.get_json(silent=True)
    if not isinstance(body, list):
        return jsonify({"error": "Expected a JSON array of edits."}), 400
    if not body:
        return jsonify({"applied": 0, "skipped": [], "newCategories": []})

    try:
        sheet, cfg = _load_cfg_and_sheet()
        tx_rows = sheets_client.read_all_rows(sheet, config.TRANSACTIONS_TAB)
        applied, skipped, new_categories = apply_edits(sheet, cfg, tx_rows, body)
    except Exception as e:
        return jsonify({"error": f"Could not reach the Sheet: {e}"}), 502

    return jsonify({"applied": applied, "skipped": skipped, "newCategories": new_categories})


def main():
    url = f"http://{HOST}:{PORT}/"
    webbrowser.open(url)
    app.run(host=HOST, port=PORT, debug=False)


if __name__ == "__main__":
    main()
