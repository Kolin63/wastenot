"""
app.py – WasteNot Flask web application.

Routes
------
GET  /                           HTML dashboard
GET  /api/data                   JSON – most recent sensor reading
GET  /api/history                JSON – rolling history (last 100 readings)
GET  /api/camera/stream          MJPEG live camera feed
GET  /api/camera/status          JSON – camera availability and mock mode flag
POST /api/camera/capture         Capture a still frame and recognise food
GET  /api/fridge                 JSON – current fridge inventory
POST /api/fridge                 JSON – add an item to the fridge
DELETE /api/fridge/<id>          JSON – remove an item from the fridge
GET  /api/fridge/recommendations JSON – "eat first" spoilage recommendations
"""

import time

import camera
import food_recognition
import fridge
import sensor
from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)


# ── CORS ──────────────────────────────────────────────────────────────────────
# Allow any origin to read the API so the static GitHub Pages dashboard can
# fetch live data from this device.  All cross-origin pre-flight OPTIONS
# requests are answered here as well.

@app.before_request
def handle_preflight():
    """Answer CORS pre-flight OPTIONS requests immediately."""
    if request.method == "OPTIONS":
        resp = app.make_default_options_response()
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        return resp


@app.after_request
def add_cors_headers(response):
    """Attach CORS headers to every response (including streaming ones)."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return response


# ── Sensor routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template(
        "index.html",
        alert_threshold=sensor.TVOC_ALERT_THRESHOLD,
    )


@app.route("/demo")
def demo():
    """Demo controls page – only available when running in mock mode."""
    if not sensor.MOCK_MODE:
        return redirect(url_for("index"))
    return render_template("demo.html")


@app.route("/api/data")
def api_data():
    data = dict(sensor.get_current())
    data["alert_threshold"] = sensor.TVOC_ALERT_THRESHOLD
    return jsonify(data)


@app.route("/api/history")
def api_history():
    history = sensor.get_history()
    # Return at most the last 100 data-points to keep payload small
    return jsonify(history[-100:])


# ── Camera routes ─────────────────────────────────────────────────────────────

def _mjpeg_generator():
    """Yield multipart JPEG frames for the live MJPEG stream."""
    while True:
        frame = camera.get_frame()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        )
        time.sleep(0.2)


@app.route("/api/camera/stream")
def camera_stream():
    """MJPEG stream of the ArduCam feed (or mock frames in demo mode)."""
    return Response(
        _mjpeg_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/api/camera/capture", methods=["POST"])
def camera_capture():
    """
    Capture a still frame and run food recognition on it.

    Returns the recognition result (label, confidence, candidates) or an
    error JSON with an appropriate HTTP status code.
    """
    image_bytes = camera.capture_snapshot()
    if image_bytes is None:
        return jsonify({"error": "Camera not available"}), 503

    result = food_recognition.recognize(image_bytes)
    if result is None:
        return jsonify({"error": "Food recognition failed"}), 500

    return jsonify(result)


@app.route("/api/camera/status")
def camera_status():
    """Return camera availability and whether it is running in mock mode."""
    return jsonify(camera.get_status())


# ── Fridge inventory routes ────────────────────────────────────────────────────

@app.route("/api/fridge", methods=["GET"])
def api_fridge_get():
    """Return the full fridge inventory."""
    return jsonify(fridge.get_inventory())


@app.route("/api/fridge", methods=["POST"])
def api_fridge_add():
    """
    Add a food item to the fridge.

    Expected JSON body::

        {"label": "banana", "quantity": 2, "notes": "organic"}

    Only ``label`` is required.
    """
    data = request.get_json(force=True, silent=True) or {}
    label = str(data.get("label") or "").strip()
    if not label:
        return jsonify({"error": "label is required"}), 400
    quantity = int(data.get("quantity", 1))
    notes = str(data.get("notes", ""))
    item = fridge.add_item(label, quantity, notes)
    return jsonify(item), 201


@app.route("/api/fridge/<int:item_id>", methods=["DELETE"])
def api_fridge_remove(item_id: int):
    """Remove a fridge item by its numeric ID."""
    removed = fridge.remove_item(item_id)
    if not removed:
        return jsonify({"error": "Item not found"}), 404
    return jsonify({"removed": item_id})


@app.route("/api/sensor/mock-tvoc", methods=["POST"])
def api_set_mock_tvoc():
    """
    Override the simulated TVOC reading in demo/mock mode.

    Expected JSON body::

        {"tvoc": 250}

    Pass ``{"tvoc": null}`` to resume automatic simulation.
    Only available when the application is running in demo/mock mode.
    """
    if not sensor.MOCK_MODE:
        return jsonify({"error": "Only available in demo mode"}), 403
    data = request.get_json(force=True, silent=True) or {}
    raw = data.get("tvoc")
    if raw is None:
        sensor.set_mock_tvoc(None)
        return jsonify({"tvoc": None})
    try:
        tvoc = int(raw)
    except (ValueError, TypeError):
        return jsonify({"error": "tvoc must be a number"}), 400
    if not 0 <= tvoc <= 1000:
        return jsonify({"error": "tvoc must be between 0 and 1000"}), 400
    sensor.set_mock_tvoc(tvoc)
    return jsonify({"tvoc": tvoc})


@app.route("/api/fridge/recommendations")
def api_recommendations():
    """
    Return fridge items ranked by spoilage urgency.

    Uses the current TVOC reading and each item's ethylene sensitivity to
    score and order the items (highest urgency first).
    """
    reading = sensor.get_current()
    recs = fridge.get_recommendations(
        tvoc=reading.get("tvoc", 0),
        alert_threshold=sensor.TVOC_ALERT_THRESHOLD,
    )
    return jsonify(recs)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    fridge.init()
    sensor.start()
    camera.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
