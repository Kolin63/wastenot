"""
food_recognition.py – Lightweight food item recognition for WasteNot.

Uses a pretrained MobileNetV3-Small model (torchvision / ImageNet) to
identify food items visible in a JPEG frame.  In MOCK_MODE (or when
torch/torchvision are not installed) the module returns plausible
randomised results so the dashboard can be fully exercised without a GPU
or model weights.
"""

import io
import os
import random
from typing import Optional

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
# Public API
# ---------------------------------------------------------------------------

def recognize(image_bytes: bytes) -> Optional[dict]:
    """
    Identify the food item(s) visible in *image_bytes* (JPEG or PNG).

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
    if MOCK_MODE or not _load_model():
        return _mock_result()

    try:
        import torch  # type: ignore
        from PIL import Image  # type: ignore

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
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


def _mock_result() -> dict:
    """Return a plausible randomised food recognition result for demo mode."""
    common = ALL_FOOD_LABELS[:25]  # Most recognisable everyday grocery items
    label = random.choice(common)
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
