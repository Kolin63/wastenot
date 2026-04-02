"""
test_food_recognition.py – Unit tests for food_recognition.py

Covers:
 - White-balance correction neutralises a severe colour bias
 - _preprocess_jpeg produces valid JPEG bytes
 - _shape_heuristic correctly classifies a synthetic yellow-banana image
 - _shape_heuristic correctly classifies a blue-banana image *after*
   white-balance correction (the core colour-insensitivity requirement)
 - recognize() in mock mode returns a well-formed result dict
 - recognize() in mock mode returns a banana result for a banana image
"""

import io
import os

import numpy as np
import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Helpers to build synthetic test images
# ---------------------------------------------------------------------------

def _make_jpeg(array: np.ndarray, quality: int = 90) -> bytes:
    """Encode an RGB numpy array as JPEG bytes."""
    buf = io.BytesIO()
    Image.fromarray(array.astype(np.uint8)).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _banana_shape(h: int = 120, w: int = 320, color_rgb=(220, 200, 50)) -> np.ndarray:
    """
    Return an RGB image containing an elongated ellipse (banana shape) filled
    with *color_rgb* on a white background.
    """
    import cv2

    img = np.ones((h, w, 3), dtype=np.uint8) * 255
    cx, cy = w // 2, h // 2
    # draw a wide ellipse that looks like a banana
    cv2.ellipse(img, (cx, cy), (w // 2 - 10, h // 4), 0, 0, 360, color_rgb[::-1], -1)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def _make_blue_banana_jpeg() -> bytes:
    """
    Simulate the camera's colour shift by applying a uniform blue-channel
    boost to an entire scene (neutral-gray background + yellow banana ellipse).

    Realistic scene-level shifting is essential for the Gray World algorithm:
    a plain white background has equal RGB channels and produces no correction
    signal, whereas a gray background lets the algorithm detect and reverse the
    per-channel bias introduced by the miscalibrated camera.
    """
    import cv2 as _cv2

    h, w = 120, 320
    # Scene: neutral gray background + yellow banana (BGR: B=50, G=200, R=220)
    img_bgr = np.ones((h, w, 3), dtype=np.uint8) * 128
    cx, cy = w // 2, h // 2
    _cv2.ellipse(img_bgr, (cx, cy), (w // 2 - 10, h // 4), 0, 0, 360, (50, 200, 220), -1)
    # Simulate the camera's blue-channel boost (ArduCam with wrong white balance)
    img_float = img_bgr.astype(np.float32)
    img_float[:, :, 0] = np.clip(img_float[:, :, 0] * 2.5, 0, 255)  # B × 2.5
    img_float[:, :, 2] = np.clip(img_float[:, :, 2] * 0.4, 0, 255)  # R × 0.4
    img_rgb = _cv2.cvtColor(img_float.astype(np.uint8), _cv2.COLOR_BGR2RGB)
    return _make_jpeg(img_rgb)


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

import food_recognition as fr  # noqa: E402


# ---------------------------------------------------------------------------
# White-balance correction tests
# ---------------------------------------------------------------------------

class TestCorrectWhiteBalance:
    def test_neutral_image_unchanged(self):
        """A perfectly grey image has equal channel means – scales are all 1."""
        grey = np.full((10, 10, 3), 128, dtype=np.uint8)
        result = fr._correct_white_balance(grey)
        np.testing.assert_array_equal(result, grey)

    def test_corrects_strong_blue_bias(self):
        """An image with a strong blue bias should be corrected so that R≈G≈B."""
        # Craft an image where blue channel is 4× brighter than R and G
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        img[:, :, 0] = 50   # R
        img[:, :, 1] = 50   # G
        img[:, :, 2] = 200  # B  ← strong blue bias (as seen with the banana camera)
        corrected = fr._correct_white_balance(img)
        r_mean = corrected[:, :, 0].mean()
        g_mean = corrected[:, :, 1].mean()
        b_mean = corrected[:, :, 2].mean()
        # After correction the three channel means should be close to equal
        assert abs(r_mean - b_mean) < 10, f"R mean {r_mean} and B mean {b_mean} should be close"
        assert abs(g_mean - b_mean) < 10, f"G mean {g_mean} and B mean {b_mean} should be close"

    def test_output_dtype_uint8(self):
        img = np.random.randint(0, 256, (20, 20, 3), dtype=np.uint8)
        result = fr._correct_white_balance(img)
        assert result.dtype == np.uint8

    def test_output_clipped_to_255(self):
        """No pixel value should exceed 255 after scaling."""
        img = np.full((5, 5, 3), 10, dtype=np.uint8)
        img[:, :, 0] = 1   # extremely dim R → will be scaled up heavily
        result = fr._correct_white_balance(img)
        assert result.max() <= 255


# ---------------------------------------------------------------------------
# _preprocess_jpeg tests
# ---------------------------------------------------------------------------

class TestPreprocessJpeg:
    def test_returns_bytes(self):
        """_preprocess_jpeg should always return bytes."""
        yellow = _banana_shape()
        jpeg = _make_jpeg(yellow)
        result = fr._preprocess_jpeg(jpeg)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_output_is_valid_jpeg(self):
        """The returned bytes should be decodable as a JPEG image."""
        yellow = _banana_shape()
        jpeg = _make_jpeg(yellow)
        result = fr._preprocess_jpeg(jpeg)
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_falls_back_on_bad_input(self):
        """Invalid bytes should be returned unchanged (no exception raised)."""
        bad = b"not a jpeg"
        result = fr._preprocess_jpeg(bad)
        assert result == bad


# ---------------------------------------------------------------------------
# _shape_heuristic tests
# ---------------------------------------------------------------------------

class TestShapeHeuristic:
    def test_yellow_banana_detected(self):
        """A yellow elongated shape should be classified as banana."""
        jpeg = _make_jpeg(_banana_shape(color_rgb=(220, 200, 50)))
        label = fr._shape_heuristic(jpeg)
        assert label == "banana", f"Expected 'banana', got {label!r}"

    def test_blue_banana_detected_after_wb_correction(self):
        """
        Core requirement: a blue-shifted banana image should be classified
        as 'banana' after white-balance correction is applied first.
        """
        raw_jpeg = _make_blue_banana_jpeg()
        corrected_jpeg = fr._preprocess_jpeg(raw_jpeg)
        label = fr._shape_heuristic(corrected_jpeg)
        assert label == "banana", (
            f"Expected 'banana' after white-balance correction, got {label!r}"
        )


# ---------------------------------------------------------------------------
# recognize() integration tests (always runs in mock mode for this test file)
# ---------------------------------------------------------------------------

class TestRecognize:
    """All tests here force mock mode by patching the module-level flag."""

    def _force_mock(self, monkeypatch):
        monkeypatch.setattr(fr, "MOCK_MODE", True)

    def test_returns_dict_in_mock_mode(self, monkeypatch):
        self._force_mock(monkeypatch)
        jpeg = _make_jpeg(_banana_shape())
        result = fr.recognize(jpeg)
        assert isinstance(result, dict)

    def test_result_has_required_keys(self, monkeypatch):
        self._force_mock(monkeypatch)
        jpeg = _make_jpeg(_banana_shape())
        result = fr.recognize(jpeg)
        assert "label" in result
        assert "confidence" in result
        assert "candidates" in result

    def test_confidence_in_range(self, monkeypatch):
        self._force_mock(monkeypatch)
        jpeg = _make_jpeg(_banana_shape())
        result = fr.recognize(jpeg)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_label_is_known_food(self, monkeypatch):
        self._force_mock(monkeypatch)
        jpeg = _make_jpeg(_banana_shape())
        result = fr.recognize(jpeg)
        assert result["label"] in fr.ALL_FOOD_LABELS

    def test_banana_image_returns_banana(self, monkeypatch):
        """
        In mock mode, recognize() should identify an elongated yellow shape
        as a banana (via the shape heuristic, not random guessing).
        """
        self._force_mock(monkeypatch)
        jpeg = _make_jpeg(_banana_shape(color_rgb=(220, 200, 50)))
        result = fr.recognize(jpeg)
        assert result["label"] == "banana", (
            f"Expected 'banana' for banana-shaped yellow image, got {result['label']!r}"
        )

    def test_blue_banana_returns_banana(self, monkeypatch):
        """
        Core requirement: a colour-shifted (blue) banana image should still
        be identified as banana after white-balance correction.
        """
        self._force_mock(monkeypatch)
        result = fr.recognize(_make_blue_banana_jpeg())
        assert result["label"] == "banana", (
            f"Expected 'banana' for blue-shifted banana image, got {result['label']!r}"
        )

    def test_candidates_list_non_empty(self, monkeypatch):
        self._force_mock(monkeypatch)
        jpeg = _make_jpeg(_banana_shape())
        result = fr.recognize(jpeg)
        assert len(result["candidates"]) >= 1

    def test_first_candidate_matches_label(self, monkeypatch):
        self._force_mock(monkeypatch)
        jpeg = _make_jpeg(_banana_shape())
        result = fr.recognize(jpeg)
        assert result["candidates"][0]["label"] == result["label"]
