"""
Metal Fabrication Nesting Microservice
Handles 1D (linear) and 2D (panel) cutting optimization
"""

from flask import Flask, request, jsonify
from nesting_1d import nest_1d
from nesting_2d import nest_2d
from utils import validate_payload, build_summary
import traceback

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "metal-nesting-api", "version": "1.0.0"})


@app.route("/nest", methods=["POST"])
def nest():
    """
    Main nesting endpoint. Accepts a JSON payload with parts and stock definitions,
    returns a full cut plan with stock usage, cut details, remnants, and SVG layouts.
    """
    try:
        payload = request.get_json()
        if not payload:
            return jsonify({"error": "No JSON payload received"}), 400

        errors = validate_payload(payload)
        if errors:
            return jsonify({"error": "Invalid payload", "details": errors}), 400

        project_id   = payload.get("project_id")
        run_number   = payload.get("run_number", 1)
        kerf_1d      = float(payload.get("kerf_1d", 0.125))
        kerf_2d      = float(payload.get("kerf_2d", 0.125))
        parts_1d     = payload.get("parts_1d", [])
        parts_2d     = payload.get("parts_2d", [])
        stock_1d     = payload.get("stock_1d", [])
        stock_2d     = payload.get("stock_2d", [])

        results_1d = []
        results_2d = []

        # --- 1D Nesting ---
        if parts_1d and stock_1d:
            results_1d = nest_1d(parts_1d, stock_1d, kerf_1d)

        # --- 2D Nesting ---
        if parts_2d and stock_2d:
            results_2d = nest_2d(parts_2d, stock_2d, kerf_2d)

        summary = build_summary(results_1d, results_2d)

        return jsonify({
            "project_id":  project_id,
            "run_number":  run_number,
            "summary":     summary,
            "results_1d":  results_1d,
            "results_2d":  results_2d
        }), 200

    except Exception as e:
        return jsonify({
            "error": "Internal server error",
            "detail": str(e),
            "trace": traceback.format_exc()
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
