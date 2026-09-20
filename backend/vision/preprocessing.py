"""
Shared low-level image utilities: loading, resizing, colour-space helpers.
Pure OpenCV / NumPy — no network or model downloads required.
"""

from __future__ import annotations

import logging
from typing import Tuple

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger("aranya.vision")

MAX_DIM = 1024


def pil_to_bgr(pil_image: Image.Image) -> np.ndarray:
    """Convert a PIL image (any mode) to an OpenCV BGR ndarray."""
    rgb = np.array(pil_image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def bgr_to_rgb(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def resize_max_dim(image: np.ndarray, max_dim: int = MAX_DIM) -> np.ndarray:
    """Downscale (never upscale) so the longest side is at most max_dim."""
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= max_dim:
        return image
    scale = max_dim / float(longest)
    new_size = (int(w * scale), int(h * scale))
    return cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)


def denoise(image: np.ndarray) -> np.ndarray:
    """Light denoising to stabilise colour/texture statistics."""
    return cv2.bilateralFilter(image, d=7, sigmaColor=50, sigmaSpace=50)


def normalize_illumination(bgr: np.ndarray) -> np.ndarray:
    """
    Reduce the effect of uneven lighting by equalising the L channel in LAB
    space. Helps make colour-based disease/biomarker thresholds more stable
    across different phone cameras / lighting conditions.
    """
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    lab = cv2.merge([l, a, b])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def preprocess(bgr: np.ndarray) -> np.ndarray:
    """Standard preprocessing pipeline used before analysis."""
    img = resize_max_dim(bgr)
    img = denoise(img)
    img = normalize_illumination(img)
    return img


def largest_foreground_mask(bgr: np.ndarray, iterations: int = 5) -> np.ndarray:
    """
    Segment the dominant foreground object (leaf, animal, etc.) from a
    roughly-centred photo using GrabCut, seeded with a centred rectangle.
    Returns a uint8 mask (255 = foreground, 0 = background).

    This is classical, deterministic computer vision (no trained detector) —
    it works reasonably well for typical close-up phone photos where the
    subject fills most of the frame, which is the intended capture pattern
    for this app.
    """
    h, w = bgr.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)

    margin_x, margin_y = int(w * 0.05), int(h * 0.05)
    rect = (margin_x, margin_y, w - 2 * margin_x, h - 2 * margin_y)

    try:
        cv2.grabCut(bgr, mask, rect, bgd_model, fgd_model, iterations, cv2.GC_INIT_WITH_RECT)
        fg_mask = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype("uint8")
    except cv2.error as exc:
        logger.warning("GrabCut failed (%s); falling back to full-frame mask", exc)
        fg_mask = np.full((h, w), 255, dtype="uint8")

    # Fallback: if GrabCut collapses to (near) nothing, use the whole frame.
    if fg_mask.sum() < 0.02 * 255 * h * w:
        fg_mask = np.full((h, w), 255, dtype="uint8")

    # Clean up small holes/noise.
    kernel = np.ones((5, 5), np.uint8)
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
    return fg_mask


def largest_contour_bbox(mask: np.ndarray) -> Tuple[int, int, int, int]:
    """Bounding box (x, y, w, h) of the largest contour in a binary mask."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        h, w = mask.shape[:2]
        return 0, 0, w, h
    largest = max(contours, key=cv2.contourArea)
    return cv2.boundingRect(largest)
