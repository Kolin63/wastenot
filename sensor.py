"""
sensor.py – SGP30 sensor interface for WasteNot.

Runs a background thread that samples the SGP30 every second and
maintains a rolling history of readings.  When the hardware is not
present (or MOCK_MODE=true is set) the module falls back to a
simulated signal so the web application can be demonstrated on any
machine.
"""

import math
import os
import random
import threading
import time
from collections import deque
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration (can be overridden via environment variables)
# ---------------------------------------------------------------------------
MOCK_MODE: bool = os.environ.get("MOCK_MODE", "false").lower() == "true"

# TVOC threshold (ppb) above which an alert is triggered
TVOC_ALERT_THRESHOLD: int = int(os.environ.get("TVOC_ALERT_THRESHOLD", "200"))

# How many readings to keep in the rolling history
HISTORY_SIZE: int = int(os.environ.get("HISTORY_SIZE", "300"))

# Seconds to pause between samples
SAMPLE_INTERVAL: float = float(os.environ.get("SAMPLE_INTERVAL", "1.0"))

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
readings_history: deque = deque(maxlen=HISTORY_SIZE)
current_reading: dict = {
    "tvoc": 0,
    "eco2": 400,
    "timestamp": None,
    "alert": False,
    "status": "initializing",
}
SENSOR_AVAILABLE: bool = False
_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Try to import the real Adafruit SGP30 library
# ---------------------------------------------------------------------------
_sgp30 = None

if not MOCK_MODE:
    try:
        import board  # type: ignore
        import busio  # type: ignore
        import adafruit_sgp30  # type: ignore

        _i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        _sgp30 = adafruit_sgp30.Adafruit_SGP30(_i2c)
        _sgp30.iaq_init()
        SENSOR_AVAILABLE = True
        print("SGP30 sensor initialized successfully.")
    except Exception as exc:
        print(f"Warning: Could not initialise SGP30 sensor: {exc}")
        print("Falling back to mock mode.")
        MOCK_MODE = True
else:
    print("Mock mode enabled – using simulated sensor data.")


# ---------------------------------------------------------------------------
# Reading functions
# ---------------------------------------------------------------------------

def _read_hardware() -> tuple[int, int]:
    """Read one sample from the real SGP30."""
    return int(_sgp30.TVOC), int(_sgp30.eCO2)


def _read_mock() -> tuple[int, int]:
    """Generate a plausible simulated reading."""
    t = time.monotonic()
    # Gentle sinusoidal drift + small noise
    tvoc = 60 + 40 * math.sin(t / 90) + random.gauss(0, 8)
    eco2 = 450 + 30 * math.sin(t / 120) + random.gauss(0, 5)
    # Occasional spike – simulates a burst of ethylene from ripe fruit
    if random.random() < 0.015:
        tvoc += random.uniform(120, 350)
    return max(0, int(tvoc)), max(400, int(eco2))


# ---------------------------------------------------------------------------
# Background sensor loop
# ---------------------------------------------------------------------------

def _sensor_loop() -> None:
    """Continuously read the sensor and update shared state."""
    warmup_seconds = 15
    start_time = time.monotonic()

    while True:
        try:
            elapsed = time.monotonic() - start_time
            if MOCK_MODE:
                tvoc, eco2 = _read_mock()
                status = "mock"
            elif elapsed < warmup_seconds:
                # SGP30 needs ~15 s warm-up; readings before that are
                # unreliable so we still return them but flag the status.
                tvoc, eco2 = _read_hardware()
                status = "warming_up"
            else:
                tvoc, eco2 = _read_hardware()
                status = "ok"

            alert = tvoc >= TVOC_ALERT_THRESHOLD
            reading = {
                "tvoc": tvoc,
                "eco2": eco2,
                "timestamp": datetime.now().isoformat(),
                "alert": alert,
                "status": status,
            }
            with _lock:
                current_reading.update(reading)
                readings_history.append(reading)

        except Exception as exc:  # pragma: no cover
            print(f"Sensor read error: {exc}")
            with _lock:
                current_reading["status"] = "error"

        time.sleep(SAMPLE_INTERVAL)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_current() -> dict:
    """Return a snapshot of the most recent reading."""
    with _lock:
        return dict(current_reading)


def get_history() -> list:
    """Return the full rolling history as a list."""
    with _lock:
        return list(readings_history)


def start() -> None:
    """Start the background sensor thread (call once at application start)."""
    thread = threading.Thread(target=_sensor_loop, daemon=True, name="sensor-loop")
    thread.start()
