"""
app.py – WasteNot Flask web application.

Routes
------
GET /                  HTML dashboard
GET /api/data          JSON – most recent sensor reading
GET /api/history       JSON – rolling history (last 100 readings)
"""

import sensor
from flask import Flask, jsonify, render_template

app = Flask(__name__)


@app.route("/")
def index():
    return render_template(
        "index.html",
        mock_mode=sensor.MOCK_MODE,
        alert_threshold=sensor.TVOC_ALERT_THRESHOLD,
    )


@app.route("/api/data")
def api_data():
    return jsonify(sensor.get_current())


@app.route("/api/history")
def api_history():
    history = sensor.get_history()
    # Return at most the last 100 data-points to keep payload small
    return jsonify(history[-100:])


if __name__ == "__main__":
    sensor.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
