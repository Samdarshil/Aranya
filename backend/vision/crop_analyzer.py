"""
CROP DISEASE / RISK SCREENING PIPELINE
---------------------------------------
Honest description of what this does:

  * This is a classical computer-vision pipeline (OpenCV/NumPy) built from
    colour, texture and lesion-shape indicators. It is REAL, deterministic
    image analysis — not a placeholder / random number generator.
  * It is NOT a trained deep-learning disease classifier (e.g. a CNN trained
    on PlantVillage). No such model ships with this prototype because this
    development environment has no internet access to fetch a licensed
    pretrained model or dataset. The pipeline is written so a real trained
    classifier can be dropped in later (see `predict_with_deep_model`
    stub at the bottom) without changing the rest of the app.
  * Crop species is NOT auto-identified by a model — the user selects it
    from a dropdown. We do not fabricate species recognition we don't have.
  * "Disease name" is reported as a *pattern category* (e.g. "leaf-spot /
    fungal-pattern indicators") derived from which indicators fired, not a
    certified diagnosis of a specific pathogen.

Indicators computed on the segmented leaf/plant region:
  1. Colour deviation  — fraction of pixels that fall outside the healthy
     green band in HSV (captures yellowing/chlorosis/browning).
  2. Lesion / spot detection — dark or high-saturation-anomaly blobs,
     found via adaptive thresholding + contour filtering.
  3. Texture irregularity — local variance of the Laplacian, which spikes
     around lesion edges, necrotic patches and mildew-like textures.

These three are combined into an overall "affected area %" and a rule-based
risk category, which keeps the system fully explainable (no black box).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Tuple

import cv2
import numpy as np

from backend.core.vision_config import CROP_RISK_THRESHOLDS
from backend.vision.preprocessing import preprocess, largest_foreground_mask
from backend.vision.visualization import draw_boxes, heatmap_overlay

logger = logging.getLogger("aranya.vision.crop")

# Healthy-leaf green band in HSV (OpenCV: H 0-179, S 0-255, V 0-255)
_HEALTHY_GREEN_LOWER = np.array([30, 40, 30])
_HEALTHY_GREEN_UPPER = np.array([95, 255, 255])

MIN_SPOT_AREA_FRACTION = 0.0008  # ignore specks smaller than this fraction of leaf area


@dataclass
class CropIndicator:
    name: str
    detected: bool
    detail: str


@dataclass
class CropAnalysisResult:
    crop_name: str
    status: str                 # "Healthy" | "At Risk" | "Diseased / High Risk"
    status_emoji: str
    condition_summary: str
    indicators: List[CropIndicator]
    affected_area_pct: float
    heuristic_confidence: float
    recommendation: str
    overlay_image: np.ndarray   # BGR image with visual explanation drawn on
    leaf_area_pct_of_frame: float
    is_demo: bool = False
    raw_metrics: dict = field(default_factory=dict)


def _status_from_affected_area(pct: float) -> Tuple[str, str]:
    t = CROP_RISK_THRESHOLDS
    if pct < t["healthy_max"]:
        return "Healthy", "🟢"
    if pct < t["at_risk_max"]:
        return "At Risk", "🟠"
    return "Diseased / High Risk", "🔴"


def _detect_leaf_mask(bgr: np.ndarray) -> np.ndarray:
    """Foreground segmentation restricted to plausible plant-matter colours."""
    fg = largest_foreground_mask(bgr)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    # Broad plant-matter band: greens through yellow/brown (diseased tissue
    # is often yellow/brown, so we deliberately include that range here and
    # let the *colour deviation* indicator flag it as abnormal separately).
    plant_lower = np.array([15, 25, 20])
    plant_upper = np.array([100, 255, 255])
    plant_mask = cv2.inRange(hsv, plant_lower, plant_upper)
    combined = cv2.bitwise_and(fg, plant_mask)
    if combined.sum() < 0.03 * 255 * bgr.shape[0] * bgr.shape[1]:
        # Too little plant-coloured area found inside the foreground mask —
        # fall back to the plant-colour mask alone.
        combined = plant_mask
    kernel = np.ones((5, 5), np.uint8)
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel)
    return combined


def _colour_deviation_mask(bgr: np.ndarray, leaf_mask: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    healthy = cv2.inRange(hsv, _HEALTHY_GREEN_LOWER, _HEALTHY_GREEN_UPPER)
    abnormal_colour = cv2.bitwise_and(cv2.bitwise_not(healthy), leaf_mask)
    return abnormal_colour


def _lesion_spots(bgr: np.ndarray, leaf_mask: np.ndarray) -> Tuple[np.ndarray, List[Tuple[int, int, int, int]]]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray_masked = cv2.bitwise_and(gray, gray, mask=leaf_mask)

    blur = cv2.GaussianBlur(gray_masked, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 6
    )
    thresh = cv2.bitwise_and(thresh, leaf_mask)

    kernel = np.ones((3, 3), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    leaf_area = max(int(leaf_mask.sum() / 255), 1)
    min_area = MIN_SPOT_AREA_FRACTION * leaf_area

    boxes = []
    spot_mask = np.zeros_like(leaf_mask)
    for c in contours:
        area = cv2.contourArea(c)
        if area >= min_area:
            x, y, w, h = cv2.boundingRect(c)
            boxes.append((x, y, w, h))
            cv2.drawContours(spot_mask, [c], -1, 255, -1)

    return spot_mask, boxes


def _texture_irregularity(bgr: np.ndarray, leaf_mask: np.ndarray) -> Tuple[float, np.ndarray]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    lap_abs = np.abs(lap)

    # Local variance map via box filter on squared values.
    k = 9
    mean = cv2.blur(lap_abs, (k, k))
    mean_sq = cv2.blur(lap_abs ** 2, (k, k))
    local_var = np.clip(mean_sq - mean ** 2, 0, None)

    mask_bool = leaf_mask.astype(bool)
    if not mask_bool.any():
        return 0.0, np.zeros_like(gray)

    values = local_var[mask_bool]
    p95 = float(np.percentile(values, 95)) or 1.0
    norm_map = np.clip(local_var / p95, 0, 1)

    # Fraction of leaf pixels with high local texture variance = irregular.
    high_var_frac = float((values > 0.5 * p95).mean()) * 100
    return high_var_frac, norm_map


def analyze_crop_image(bgr: np.ndarray, crop_name: str) -> CropAnalysisResult:
    """Run the full crop-screening pipeline on a preprocessed BGR image."""
    img = preprocess(bgr)
    leaf_mask = _detect_leaf_mask(img)
    leaf_area_pct = float(leaf_mask.sum() / 255) / (img.shape[0] * img.shape[1]) * 100

    colour_mask = _colour_deviation_mask(img, leaf_mask)
    spot_mask, spot_boxes = _lesion_spots(img, leaf_mask)
    texture_pct, texture_map = _texture_irregularity(img, leaf_mask)

    leaf_pixels = max(int(leaf_mask.sum() / 255), 1)
    colour_pct = float(colour_mask.sum() / 255) / leaf_pixels * 100
    spot_pct = float(spot_mask.sum() / 255) / leaf_pixels * 100

    # Combined abnormal-tissue mask (union of colour deviation and lesions).
    combined_abnormal = cv2.bitwise_or(colour_mask, spot_mask)
    affected_area_pct = float(combined_abnormal.sum() / 255) / leaf_pixels * 100
    affected_area_pct = round(min(affected_area_pct, 100.0), 1)

    status, emoji = _status_from_affected_area(affected_area_pct)

    indicators = [
        CropIndicator("Abnormal colour (yellowing / browning)",
                       colour_pct > 8.0,
                       f"{colour_pct:.1f}% of leaf area shows non-healthy-green colour"),
        CropIndicator("Leaf spots / lesions",
                       len(spot_boxes) > 0,
                       f"{len(spot_boxes)} candidate spot region(s) detected"),
        CropIndicator("Texture irregularity",
                       texture_pct > 12.0,
                       f"{texture_pct:.1f}% of leaf area shows irregular texture"),
    ]

    detected_names = [i.name for i in indicators if i.detected]
    if status == "Healthy":
        condition_summary = "No significant disease indicators detected"
    elif detected_names:
        condition_summary = "Early/active disease pattern detected (" + ", ".join(detected_names) + ")"
    else:
        condition_summary = "Elevated abnormal-area indicators detected"

    # Heuristic confidence: how much of the frame is leaf (better segmentation
    # -> more trustworthy measurement) plus indicator agreement. This is a
    # transparency signal, not a model probability.
    agreement = len(detected_names) / len(indicators) if status != "Healthy" else 1.0
    seg_quality = min(leaf_area_pct / 35.0, 1.0)  # assume good photos fill ~35%+ of frame
    heuristic_confidence = round(min(0.5 + 0.3 * seg_quality + 0.2 * agreement, 0.97) * 100, 0)

    if status == "Healthy":
        recommendation = ("Plant appears healthy based on visual indicators. "
                           "Continue routine monitoring.")
    elif status == "At Risk":
        recommendation = ("Inspect affected plants closely and re-scan in a few days "
                           "to track progression. Seek confirmation from an agricultural "
                           "expert if symptoms spread.")
    else:
        recommendation = ("Visual indicators suggest a significant abnormality. "
                           "Isolate/monitor the affected plants and consult an "
                           "agricultural extension officer or plant pathologist promptly.")

    # --- Explainability overlay -------------------------------------------------
    overlay = heatmap_overlay(img, texture_map, alpha=0.25)
    overlay = draw_boxes(overlay, spot_boxes, color=(0, 0, 255), thickness=2,
                         labels=["spot"] * len(spot_boxes))
    leaf_outline = np.zeros_like(leaf_mask)
    contours, _ = cv2.findContours(leaf_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay, contours, -1, (0, 255, 0), 1)

    return CropAnalysisResult(
        crop_name=crop_name,
        status=status,
        status_emoji=emoji,
        condition_summary=condition_summary,
        indicators=indicators,
        affected_area_pct=affected_area_pct,
        heuristic_confidence=heuristic_confidence,
        recommendation=recommendation,
        overlay_image=overlay,
        leaf_area_pct_of_frame=round(leaf_area_pct, 1),
        raw_metrics={
            "colour_deviation_pct": round(colour_pct, 2),
            "spot_count": len(spot_boxes),
            "spot_area_pct": round(spot_pct, 2),
            "texture_irregularity_pct": round(texture_pct, 2),
        },
    )


def predict_with_deep_model(bgr: np.ndarray, crop_name: str):
    """
    Plug-in point for a real trained deep-learning classifier (e.g. a
    PyTorch CNN fine-tuned on a licensed leaf-disease dataset such as
    PlantVillage, once you have internet access / the dataset on disk).

    Intentionally NOT implemented in this prototype — we do not fabricate
    a trained model. To wire one in:

        1. Save a trained model to `models/crop_classifier.pt`.
        2. Load it here with torch.load(...).
        3. Run inference and return class + probability.
        4. Swap the call in app.py from `analyze_crop_image` to this
           function once available, or blend both signals.
    """
    raise NotImplementedError(
        "No trained deep-learning crop classifier is bundled with this "
        "prototype (no internet access to fetch/train one). Use "
        "analyze_crop_image() for the classical CV pipeline, or plug a "
        "trained model checkpoint into this function."
    )
