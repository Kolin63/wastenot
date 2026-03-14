"""
fridge.py – Fridge inventory management for WasteNot.

Maintains a JSON-backed list of food items currently in the fridge.
Each item carries an *ethylene sensitivity* score (0 = resistant,
1 = very sensitive) which is used together with the current TVOC
reading to rank foods by spoilage risk and generate "eat first"
recommendations.
"""

import json
import os
import threading
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_FILE: str = os.environ.get("FRIDGE_DATA_FILE", "fridge_inventory.json")

# ---------------------------------------------------------------------------
# Ethylene sensitivity scores
# Higher = food spoils faster when exposed to elevated ethylene levels.
# ---------------------------------------------------------------------------
ETHYLENE_SENSITIVITY: dict[str, float] = {
    # Very sensitive – go bad first
    "banana": 1.0,
    "avocado": 0.9,
    "mango": 0.9,
    "peach": 0.9,
    "mushroom": 0.85,
    "pear": 0.85,
    "leftovers": 0.9,
    "shrimp": 0.8,
    "tomato": 0.8,
    "broccoli": 0.8,
    "strawberry": 0.8,
    "fish": 0.75,
    "kiwi": 0.75,
    "lettuce": 0.75,
    "fig": 0.75,
    "chicken": 0.65,
    "beef": 0.6,
    "pork": 0.6,
    "blueberry": 0.6,
    "cherry": 0.55,
    # Moderately sensitive
    "sandwich": 0.6,
    "apple": 0.5,
    "grapes": 0.5,
    "watermelon": 0.4,
    "pineapple": 0.5,
    "tofu": 0.5,
    "cake": 0.5,
    "pizza": 0.5,
    "corn": 0.5,
    "artichoke": 0.5,
    "spinach": 0.7,
    "cucumber": 0.5,
    "zucchini": 0.5,
    "bell pepper": 0.45,
    "orange": 0.4,
    "celery": 0.4,
    "cabbage": 0.4,
    "milk": 0.4,
    "yogurt": 0.4,
    "juice": 0.35,
    "bread": 0.35,
    "carrot": 0.35,
    "pasta": 0.3,
    "cheese": 0.3,
    # Less sensitive
    "lemon": 0.25,
    "sweet potato": 0.25,
    "potato": 0.2,
    "onion": 0.15,
    "rice": 0.1,
    "egg": 0.1,
    "butter": 0.1,
    "garlic": 0.1,
    "chocolate": 0.1,
    "jam": 0.1,
}

DEFAULT_SENSITIVITY: float = 0.5

# Baseline urgency added to all items regardless of current ethylene level.
# This ensures even items with low sensitivity show a non-zero urgency when
# items have been in the fridge a while and should still be rotated.
_BASELINE_URGENCY_FACTOR: float = 0.25

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_inventory: list[dict[str, Any]] = []
_next_id: int = 1


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load() -> None:
    global _inventory, _next_id
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE) as f:
            data = json.load(f)
        _inventory = data.get("items", [])
        _next_id = data.get("next_id", len(_inventory) + 1)
    except Exception as exc:
        print(f"Warning: could not load fridge inventory: {exc}")


def _save() -> None:
    try:
        with open(DATA_FILE, "w") as f:
            json.dump({"items": _inventory, "next_id": _next_id}, f, indent=2)
    except Exception as exc:
        print(f"Warning: could not save fridge inventory: {exc}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init() -> None:
    """Load persisted inventory from disk.  Call once at application start."""
    with _lock:
        _load()


def get_inventory() -> list[dict]:
    """Return a snapshot of the current fridge contents."""
    with _lock:
        return list(_inventory)


def add_item(label: str, quantity: int = 1, notes: str = "") -> dict:
    """
    Add a food item to the fridge.

    Returns the newly created item dict (includes the assigned ``id``).
    """
    global _next_id
    label = label.lower().strip()
    with _lock:
        item: dict[str, Any] = {
            "id": _next_id,
            "label": label,
            "quantity": max(1, int(quantity)),
            "notes": notes.strip(),
            "added_at": datetime.now().isoformat(),
            "sensitivity": ETHYLENE_SENSITIVITY.get(label, DEFAULT_SENSITIVITY),
        }
        _inventory.append(item)
        _next_id += 1
        _save()
    return item


def remove_item(item_id: int) -> bool:
    """
    Remove a food item by its ``id``.

    Returns ``True`` if the item was found and removed, ``False`` otherwise.
    """
    global _inventory
    with _lock:
        before = len(_inventory)
        _inventory = [i for i in _inventory if i["id"] != item_id]
        changed = len(_inventory) < before
        if changed:
            _save()
    return changed


def get_recommendations(tvoc: int, alert_threshold: int) -> list[dict]:
    """
    Return inventory items ranked by spoilage urgency given current TVOC.

    Each item in the returned list gains an ``urgency_score`` field
    (0 – 1).  Items are sorted highest-urgency-first.

    The score combines:
    - The item's intrinsic ethylene sensitivity
    - The current ethylene risk ratio (tvoc / alert_threshold, capped at 1)
    """
    with _lock:
        items = list(_inventory)

    if not items:
        return []

    ethylene_risk = min(1.0, tvoc / max(1, alert_threshold))

    result = []
    for item in items:
        sens = item.get("sensitivity", DEFAULT_SENSITIVITY)
        # Urgency increases with both sensitivity and current ethylene level
        urgency = round(sens * ethylene_risk + sens * _BASELINE_URGENCY_FACTOR, 4)
        result.append({**item, "urgency_score": urgency})

    result.sort(key=lambda x: x["urgency_score"], reverse=True)
    return result
