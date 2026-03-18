"""
camera.py – Camera interface for WasteNot.

Provides a unified interface for the ArduCam 5MP-OV5647 connected via
the Raspberry Pi CSI ribbon-cable connector (picamera2).  When the
hardware is absent or MOCK_MODE=true is set the module generates
synthetic JPEG frames so the web application can be demonstrated on any
machine.
"""

import io
import os
import threading
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MOCK_MODE: bool = os.environ.get("MOCK_MODE", "false").lower() == "true"

# Interval between captured frames in seconds (default 0.2 s → ~5 fps).
# Lower values give a smoother stream but increase CPU load on the Pi.
_CAPTURE_INTERVAL: float = float(os.environ.get("CAMERA_INTERVAL", "0.2"))

# Index of the CSI camera to open.  Raspberry Pi 5 has two CSI connectors
# (CAM0 = index 0, CAM1 = index 1).  If the ribbon cable is plugged into
# the second connector, set CAMERA_INDEX=1.  Pi 3 / Pi 4 only have one
# connector so this can be left at the default of 0.
_CAMERA_INDEX: int = int(os.environ.get("CAMERA_INDEX", "0"))

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_camera = None
_camera_lock = threading.Lock()
_latest_frame: Optional[bytes] = None
_frame_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Optional library imports (graceful fallback)
# ---------------------------------------------------------------------------
_picamera2_available = False
_cv2_available = False

if not MOCK_MODE:
    try:
        from picamera2 import Picamera2  # type: ignore

        _picamera2_available = True
    except Exception:
        print("Warning: picamera2 not available – falling back to mock camera.")
        MOCK_MODE = True

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    _cv2_available = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Frame generation helpers
# ---------------------------------------------------------------------------

def _generate_mock_frame() -> bytes:
    """Return a placeholder JPEG frame for demo/mock mode."""
    if _cv2_available:
        import numpy as np

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = (22, 27, 34)  # Dark background matching the dashboard
        ts = time.strftime("%H:%M:%S")
        cv2.putText(
            frame, "MOCK CAMERA FEED",
            (140, 210), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (88, 166, 255), 2,
        )
        cv2.putText(
            frame, "Hold a food item in front of the camera",
            (70, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (139, 148, 158), 1,
        )
        cv2.putText(
            frame, f"Demo mode  {ts}",
            (220, 460), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (70, 70, 70), 1,
        )
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return bytes(buf)
    return _tiny_jpeg()


def _tiny_jpeg() -> bytes:
    """Return a minimal valid JPEG when cv2 is unavailable."""
    # 8×8 grey JPEG – valid fallback so the browser doesn't show a broken image
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x10\x0b\x0c\x0e\x0c\n\x10\x0e\r\x0e\x12\x11\x10"
        b"\x13\x18(\x1a\x18\x16\x16\x18\x310#%\x1d(O5;=<9=GHJ>BCPQO?eTSPR"
        b"\xff\xc0\x00\x0b\x08\x00\x08\x00\x08\x01\x01\x11\x00\xff\xc4\x00"
        b"\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00"
        b"\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00"
        b"\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07\"q\x14"
        b"2\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\xff\xda\x00\x08"
        b"\x01\x01\x00\x00?\x00\xf4\xbf\xff\xd9"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_frame() -> bytes:
    """Return the most recent JPEG frame (for the MJPEG stream)."""
    with _frame_lock:
        if _latest_frame is not None:
            return _latest_frame
    return _generate_mock_frame()


def capture_snapshot() -> Optional[bytes]:
    """
    Capture a single still JPEG image suitable for food recognition.

    Returns JPEG bytes, or ``None`` if the camera is unavailable.
    """
    if MOCK_MODE:
        return _generate_mock_frame()
    with _camera_lock:
        if _camera is None:
            return None
        try:
            buf = io.BytesIO()
            _camera.capture_file(buf, format="jpeg")
            return buf.getvalue()
        except Exception as exc:
            print(f"Camera snapshot error: {exc}")
            return None


# ---------------------------------------------------------------------------
# Background capture loop
# ---------------------------------------------------------------------------

def _camera_loop() -> None:
    """Continuously capture frames and expose the latest one via get_frame()."""
    global _latest_frame
    while True:
        try:
            if MOCK_MODE:
                frame = _generate_mock_frame()
            else:
                with _camera_lock:
                    if _camera is None:
                        time.sleep(1)
                        continue
                    arr = _camera.capture_array()
                if _cv2_available:
                    import numpy as np

                    _, buf = cv2.imencode(
                        ".jpg",
                        cv2.cvtColor(arr, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_JPEG_QUALITY, 70],
                    )
                    frame = bytes(buf)
                else:
                    frame = _tiny_jpeg()

            with _frame_lock:
                _latest_frame = frame

        except Exception as exc:
            print(f"Camera loop error: {exc}")
            time.sleep(1)
            continue

        time.sleep(_CAPTURE_INTERVAL)  # configurable fps (default ~5 fps)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def start() -> None:
    """Initialize the ArduCam hardware and launch the background capture thread."""
    global _camera
    if not MOCK_MODE and _picamera2_available:
        try:
            from picamera2 import Picamera2

            cam = Picamera2(_CAMERA_INDEX)
            cam.configure(
                cam.create_preview_configuration(
                    main={"size": (640, 480), "format": "RGB888"}
                )
            )
            cam.start()
            with _camera_lock:
                _camera = cam
            print("ArduCam 5MP-OV5647 (picamera2) initialized successfully.")
        except Exception as exc:
            print(f"Warning: could not initialize camera: {exc}")
            print("Camera falling back to mock mode.")

    thread = threading.Thread(target=_camera_loop, daemon=True, name="camera-loop")
    thread.start()
    print("Camera background thread started.")
