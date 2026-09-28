"""
Explainability visualisations: contour overlays, heatmaps, mask blending.
"""

from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np


def draw_contours(bgr: np.ndarray, contours: Sequence[np.ndarray],
                   color=(0, 0, 255), thickness: int = 2) -> np.ndarray:
    out = bgr.copy()
    cv2.drawContours(out, contours, -1, color, thickness)
    return out


def draw_boxes(bgr: np.ndarray, boxes: Sequence[tuple], color=(0, 140, 255),
                thickness: int = 2, labels: Sequence[str] | None = None) -> np.ndarray:
    out = bgr.copy()
    for i, (x, y, w, h) in enumerate(boxes):
        cv2.rectangle(out, (x, y), (x + w, y + h), color, thickness)
        if labels and i < len(labels):
            cv2.putText(out, labels[i], (x, max(0, y - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    return out


def mask_overlay(bgr: np.ndarray, mask: np.ndarray, color=(0, 0, 255),
                  alpha: float = 0.45) -> np.ndarray:
    """Blend a binary mask onto the image as a translucent colour overlay."""
    out = bgr.copy()
    colored = np.zeros_like(bgr)
    colored[:] = color
    mask_bool = mask.astype(bool)
    out[mask_bool] = cv2.addWeighted(bgr, 1 - alpha, colored, alpha, 0)[mask_bool]
    return out


def heatmap_overlay(bgr: np.ndarray, score_map: np.ndarray, alpha: float = 0.5) -> np.ndarray:
    """
    score_map: float32 array (same H,W as bgr) with values in [0, 1] where
    higher = more abnormal. Rendered as a JET heatmap blended over the image.
    """
    norm = np.clip(score_map, 0, 1)
    norm_u8 = (norm * 255).astype(np.uint8)
    heat = cv2.applyColorMap(norm_u8, cv2.COLORMAP_JET)
    return cv2.addWeighted(bgr, 1 - alpha, heat, alpha, 0)
