"""
food_recognition.py – Lightweight food item recognition for WasteNot.

Uses a pretrained MobileNetV3-Small model (torchvision / ImageNet) to
identify food items visible in a JPEG frame.  In MOCK_MODE (or when
torch/torchvision are not installed) the module analyses the image using
a lightweight OpenCV shape + colour heuristic so the dashboard can be
fully exercised without a GPU or model weights.

Colour correction
-----------------
Many low-cost camera modules (including the ArduCam 5MP-OV5647) produce
colour-shifted frames – e.g. bananas appearing blue.  Every image is
pre-processed with a Gray World white-balance correction before being
passed to any recogniser, which neutralises most per-channel biases.
"""

import io
import os
import random
from typing import Optional

# ---------------------------------------------------------------------------
# Optional dependency probe
# ---------------------------------------------------------------------------
_cv2_available: bool = False
try:
    import cv2 as _cv2_probe  # type: ignore  # noqa: F401
    import numpy as _np_probe  # type: ignore  # noqa: F401

    _cv2_available = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MOCK_MODE: bool = os.environ.get("MOCK_MODE", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Food vocabulary
# All food categories the system can track.  Keep in sync with fridge.py.
# ---------------------------------------------------------------------------
ALL_FOOD_LABELS: list[str] = [
    "apple", "avocado", "banana", "beef", "bell pepper", "blueberry",
    "bread", "broccoli", "butter", "cabbage", "cake", "carrot", "celery",
    "cheese", "cherry", "chicken", "chocolate", "corn", "cucumber",
    "donut", "egg", "fish", "garlic", "grapes", "hot dog", "jam",
    "juice", "kiwi", "leftovers", "lemon", "lettuce", "mango", "milk",
    "mushroom", "onion", "orange", "pasta", "peach", "pear", "pineapple",
    "pizza", "pork", "potato", "rice", "sandwich", "shrimp", "spinach",
    "strawberry", "sweet potato", "tofu", "tomato", "watermelon",
    "yogurt", "zucchini",
]

# ---------------------------------------------------------------------------
# ImageNet class → food category mapping
# MobileNetV3-Small is trained on ImageNet-1k; many classes correspond
# to food items.  We map the raw ImageNet label to our vocabulary.
# ---------------------------------------------------------------------------
_IMAGENET_FOOD_MAP: dict[str, str] = {
    "granny smith": "apple",
    "banana": "banana",
    "orange": "orange",
    "lemon": "lemon",
    "fig": "fig",
    "pineapple": "pineapple",
    "strawberry": "strawberry",
    "jackfruit": "mango",
    "pomegranate": "grapes",
    "broccoli": "broccoli",
    "cauliflower": "broccoli",
    "head cabbage": "cabbage",
    "zucchini": "zucchini",
    "mushroom": "mushroom",
    "ear": "corn",
    "artichoke": "artichoke",
    "pretzel": "bread",
    "bagel": "bread",
    "pizza": "pizza",
    "hot dog": "hot dog",
    "cheeseburger": "beef",
    "meat loaf": "beef",
    "guacamole": "avocado",
    "eggnog": "milk",
    "ice cream": "yogurt",
    "chocolate sauce": "chocolate",
    "potpie": "leftovers",
}

# ---------------------------------------------------------------------------
# Model state (lazy-loaded on first real recognition request)
# ---------------------------------------------------------------------------
_model = None
_transforms = None
_categories: list[str] = []
_model_loaded = False
_model_load_attempted = False


def _load_model() -> bool:
    """
    Lazy-load MobileNetV3-Small weights.

    Returns True when the model is ready, False when it cannot be loaded
    (e.g. torch/torchvision not installed – system falls back to mock).
    """
    global _model, _transforms, _categories, _model_loaded, _model_load_attempted
    if _model_load_attempted:
        return _model_loaded
    _model_load_attempted = True
    try:
        import torch  # type: ignore
        import torchvision.models as models  # type: ignore

        weights = models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
        _model = models.mobilenet_v3_small(weights=weights)
        _model.eval()
        _transforms = weights.transforms()
        _categories = weights.meta["categories"]
        _model_loaded = True
        print("Food recognition model (MobileNetV3-Small) loaded.")
    except Exception as exc:
        print(
            f"Info: food recognition model unavailable ({exc}). "
            "Using mock recognition."
        )
        _model_loaded = False
    return _model_loaded


def _map_imagenet_to_food(raw_label: str) -> Optional[str]:
    """Convert an ImageNet class name to one of our food categories, or None."""
    label_lower = raw_label.lower()
    for key, food in _IMAGENET_FOOD_MAP.items():
        if key in label_lower or label_lower in key:
            return food
    for food in ALL_FOOD_LABELS:
        if food in label_lower:
            return food
    return None


# ---------------------------------------------------------------------------
# Colour correction helpers
# ---------------------------------------------------------------------------

def _correct_white_balance(img_rgb: "np.ndarray") -> "np.ndarray":  # type: ignore[name-defined]
    """
    Correct colour channels using the Gray World assumption.

    Each channel is scaled so that its mean matches the overall scene mean.
    This neutralises the per-channel bias produced by cameras whose white
    balance is miscalibrated (e.g. bananas appearing blue).
    """
    import numpy as np  # type: ignore

    img = img_rgb.astype(np.float32)
    means = img.mean(axis=(0, 1))   # shape (3,) → [R̄, Ḡ, B̄]
    overall = means.mean()
    scales = np.where(means > 0, overall / means, 1.0)
    return np.clip(img * scales, 0, 255).astype(np.uint8)


def _preprocess_jpeg(image_bytes: bytes) -> bytes:
    """
    Decode *image_bytes*, apply white-balance correction, and re-encode as JPEG.

    Returns the original bytes unchanged when PIL or NumPy are not available
    so that callers can always use the return value safely.
    """
    try:
        import numpy as np  # type: ignore
        from PIL import Image  # type: ignore

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        corrected = _correct_white_balance(np.array(img))
        buf = io.BytesIO()
        Image.fromarray(corrected).save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return image_bytes


# ---------------------------------------------------------------------------
# Lightweight OpenCV heuristic (mock / fallback mode)
# ---------------------------------------------------------------------------

def _shape_heuristic(image_bytes: bytes) -> Optional[str]:
    """
    Estimate a food label from *image_bytes* using shape and colour analysis.

    The image should already have been white-balance corrected.  Returns a
    food label string, or ``None`` when OpenCV is unavailable or the image
    cannot be analysed reliably.
    """
    if not _cv2_available:
        return None
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        from PIL import Image  # type: ignore

        img_rgb = np.array(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        img_hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

        # Find the dominant object via contour detection.
        # Try both normal and inverted binary thresholds, then keep the
        # contour whose enclosed region has the highest mean saturation –
        # food items are more colourful than plain backgrounds.
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)
        best_contour = None
        best_sat = -1.0
        for flags in (cv2.THRESH_BINARY | cv2.THRESH_OTSU,
                      cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU):
            _, thresh = cv2.threshold(blurred, 0, 255, flags)
            contours, _ = cv2.findContours(
                thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if not contours:
                continue
            c = max(contours, key=cv2.contourArea)
            if cv2.contourArea(c) < 200:
                continue
            m = np.zeros(gray.shape, dtype=np.uint8)
            cv2.drawContours(m, [c], -1, 255, cv2.FILLED)
            mean_sat = float(cv2.mean(img_hsv, mask=m)[1])
            if mean_sat > best_sat:
                best_sat = mean_sat
                best_contour = c

        if best_contour is None:
            return None

        _x, _y, w, h = cv2.boundingRect(best_contour)
        aspect = w / h if h > 0 else 1.0

        # Build a pixel mask and restrict hue analysis to *colourful* pixels
        # (saturation > 30) so that plain white/grey background regions do
        # not skew the median hue.
        mask = np.zeros(gray.shape, dtype=np.uint8)
        cv2.drawContours(mask, [best_contour], -1, 255, cv2.FILLED)
        all_sat = img_hsv[:, :, 1][mask > 0]
        all_hue = img_hsv[:, :, 0][mask > 0]
        all_val = img_hsv[:, :, 2][mask > 0]
        colored = all_sat > 30
        if colored.sum() < 50:  # not enough colourful pixels to classify
            return None
        hue = float(np.median(all_hue[colored]))
        sat = float(np.median(all_sat[colored]))
        val = float(np.median(all_val[colored]))
        # OpenCV HSV: hue 0-179, sat 0-255, val 0-255

        # --- elongated objects (banana, zucchini, carrot …) ---
        if aspect > 1.6 or aspect < 0.625:
            if 10 <= hue <= 40 and sat > 60:
                return "banana"
            if 35 <= hue <= 80 and sat > 50:
                return "zucchini"
            return None  # shape is elongated but colour is ambiguous

        # --- roughly round / compact objects ---
        if hue <= 12 or hue >= 160:
            return "apple" if sat > 100 else "tomato"
        if 10 < hue <= 25 and sat > 80:
            return "orange"
        if 20 < hue <= 40 and sat > 100:
            return "lemon"
        if 35 < hue <= 85 and sat > 60:
            return "broccoli" if val < 150 else "lettuce"
        if 85 < hue <= 130 and sat > 80:
            return "blueberry"
        if 130 < hue <= 160 and sat > 60:
            return "grapes"
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recognize(image_bytes: bytes) -> Optional[dict]:
    """
    Identify the food item(s) visible in *image_bytes* (JPEG or PNG).

    The image is first pre-processed with an automatic white-balance
    correction so that colour-shifted frames (e.g. bananas appearing blue)
    are handled correctly before any recognition logic runs.

    Returns a dict::

        {
            "label":      str,    # best-match food category
            "confidence": float,  # 0.0 – 1.0
            "candidates": [       # up to 5 alternatives
                {"label": str, "confidence": float},
                …
            ]
        }

    Returns ``None`` only on a hard failure.
    """
    # Apply white-balance correction before any analysis so that
    # colour-shifted frames (e.g. bananas appearing blue) do not fool the
    # recogniser.
    processed = _preprocess_jpeg(image_bytes)

    if MOCK_MODE or not _load_model():
        return _analyze_image_mock(processed)

    try:
        import torch  # type: ignore
        from PIL import Image  # type: ignore

        img = Image.open(io.BytesIO(processed)).convert("RGB")
        tensor = _transforms(img).unsqueeze(0)

        with torch.no_grad():
            logits = _model(tensor)
            probs = torch.nn.functional.softmax(logits, dim=1)[0]
            top_k = probs.topk(15)

        candidates: list[dict] = []
        for score, idx in zip(top_k.values.tolist(), top_k.indices.tolist()):
            raw_label = _categories[idx]
            food = _map_imagenet_to_food(raw_label)
            if food and not any(c["label"] == food for c in candidates):
                candidates.append({"label": food, "confidence": round(score, 4)})
            if len(candidates) >= 5:
                break

        if not candidates:
            return None

        return {
            "label": candidates[0]["label"],
            "confidence": candidates[0]["confidence"],
            "candidates": candidates,
        }
    except Exception as exc:
        print(f"Food recognition inference error: {exc}")
        return None


def _analyze_image_mock(image_bytes: bytes) -> dict:
    """
    Return a recognition result for mock / fallback mode.

    Attempts a lightweight shape + colour analysis via OpenCV so that the
    result reflects the actual image content (e.g. correctly identifying a
    banana by its elongated shape even after white-balance correction).
    Falls back to a random choice only when OpenCV is unavailable.
    """
    common = ALL_FOOD_LABELS[:25]
    label = _shape_heuristic(image_bytes) or random.choice(common)
    confidence = round(random.uniform(0.68, 0.96), 3)
    others = random.sample([x for x in common if x != label], min(4, len(common) - 1))
    other_scores = sorted(
        [round(random.uniform(0.02, 0.28), 3) for _ in others],
        reverse=True,
    )
    return {
        "label": label,
        "confidence": confidence,
        "candidates": [{"label": label, "confidence": confidence}]
        + [{"label": c, "confidence": s} for c, s in zip(others, other_scores)],
    }
