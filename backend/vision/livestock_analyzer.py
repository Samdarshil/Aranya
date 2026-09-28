"""
LIVESTOCK HEALTH EARLY-WARNING PIPELINE
------------------------------------------
Pipeline stages (per the project spec), implemented honestly:

  Image -> Region Detection (GrabCut-based foreground segmentation; NOT a
           trained animal detector, since no such model/dataset is bundled
           in this offline environment)
        -> Biomarker Extraction (colour, texture/coat-roughness proxy,
           body-region shape proxy, skin/coat patch detection — all
           measured directly from pixels)
        -> Current-State Analysis (rule-based risk scoring, explainable)
        -> Historical Baseline (previous observations for this animal ID,
           pulled from local SQLite history)
        -> Temporal Analysis (simple statistical trend for now; the code
           path for a trained LSTM/GRU sequence model is stubbed and will
           activate automatically once enough observations exist — see
           config.MIN_SEQUENCE_LENGTH_FOR_TEMPORAL_MODEL)
        -> Risk Engine -> Explainable Health Warning

HARD SAFETY RULE: nothing in this file may claim to measure body
temperature from an RGB image, and nothing may call heuristic pixel
statistics "thermal imaging". A real thermal camera integration would be a
separate, clearly-labelled optional module.

Video input: if a short video/clip is uploaded, we sample a handful of
frames and compute the extra "movement/activity" biomarker as inter-frame
motion magnitude (a real, measurable optical-flow-based quantity) rather
than fabricating an "activity score".

SKIN/COAT ABNORMALITY DETECTION — what it does and does not do:
  `_skin_abnormality_patches()` below finds *localised* patches on the
  animal's segmented body that differ from the rest of its own coat in
  colour and/or texture — e.g. a discoloured patch, a bald/lesion-like
  spot, a rough or wound-like area. This is genuine, deterministic image
  analysis (colour-distance + adaptive-threshold texture detection,
  the same technique used for crop lesions), and it DOES localise and box
  real anomalous regions.

  It does NOT identify which disease is present. Conditions such as
  lumpy skin disease, ringworm/mange, dermatitis, ticks, or a simple wound
  can all produce a "localised skin patch" in a photo, and this pipeline
  cannot tell them apart — it has no training data or disease-specific
  visual model to do so. The output is reported as "possible skin/coat
  abnormality (pattern only)" with a named list of conditions that
  *can* present this way, not a diagnosis of any one of them. Treat this
  as "worth a closer look", not "this animal has X".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

from backend.core.vision_config import LIVESTOCK_RISK_THRESHOLDS
from backend.vision.preprocessing import preprocess, largest_foreground_mask, largest_contour_bbox
from backend.vision.visualization import draw_boxes, mask_overlay

logger = logging.getLogger("aranya.vision.livestock")


@dataclass
class LivestockIndicator:
    name: str
    detected: bool
    detail: str


SKIN_PATCH_CONDITIONS_NOTE = (
    "conditions that can visually present this way include lumpy skin disease, "
    "ringworm/mange, dermatitis, tick/parasite infestation, or a simple wound — "
    "this pipeline detects the anomalous PATCH, not which of these it is"
)

MIN_SKIN_PATCH_AREA_FRACTION = 0.004  # ignore specks smaller than this fraction of animal area


@dataclass
class LivestockBiomarkers:
    coat_mean_hsv: Tuple[float, float, float]
    coat_texture_roughness: float       # 0-100, higher = rougher/duller coat proxy
    body_region_area_pct: float         # % of frame occupied by the animal
    aspect_ratio: float                 # bbox w/h, crude posture proxy
    skin_patch_area_pct: float = 0.0    # % of animal body flagged as an anomalous patch
    skin_patch_count: int = 0
    motion_score: Optional[float] = None  # 0-100 if video frames were provided


@dataclass
class LivestockAnalysisResult:
    animal_id: str
    species: str
    risk_score: float                    # 0-100
    risk_level: str                       # "Low" | "Moderate" | "Elevated" | "High"
    risk_emoji: str
    indicators: List[LivestockIndicator]
    biomarkers: LivestockBiomarkers
    deviations: List[str]
    recommendation: str
    overlay_image: np.ndarray
    is_demo: bool = False
    raw_metrics: dict = field(default_factory=dict)


def _risk_level(score: float) -> Tuple[str, str]:
    t = LIVESTOCK_RISK_THRESHOLDS
    if score < t["low_max"]:
        return "Low Risk", "🟢"
    if score < t["moderate_max"]:
        return "Moderate Risk", "🟡"
    if score < t["elevated_max"]:
        return "Elevated Risk", "🟠"
    return "High Risk", "🔴"


def _skin_abnormality_patches(bgr: np.ndarray, mask: np.ndarray
                               ) -> Tuple[np.ndarray, List[Tuple[int, int, int, int]]]:
    """
    Find localised patches on the animal's body that differ from the rest
    of ITS OWN coat — either in colour (e.g. discolouration, bald/pink skin
    showing through) or in local texture (e.g. matted/wound-like/rough
    patches). This deliberately compares each pixel to the animal's own
    median coat colour rather than a fixed "healthy" colour, since coat
    colour varies hugely by breed.
    """
    mask_bool = mask.astype(bool)
    animal_area = max(int(mask_bool.sum()), 1)
    if animal_area < 200:
        return np.zeros_like(mask), []

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    coat_pixels = hsv[mask_bool]
    median_hsv = np.median(coat_pixels, axis=0)

    # Circular distance for hue (0-179 in OpenCV), linear for sat/val.
    h_diff = np.abs(hsv[..., 0] - median_hsv[0])
    h_diff = np.minimum(h_diff, 180 - h_diff)
    s_diff = np.abs(hsv[..., 1] - median_hsv[1])
    v_diff = np.abs(hsv[..., 2] - median_hsv[2])
    colour_dist = h_diff * 2.0 + s_diff * 0.5 + v_diff * 0.5

    # A higher percentile + floor makes this deliberately conservative:
    # ordinary anatomical shading/edges (legs, hooves, shadow under the
    # belly) should NOT trigger it — only a pixel clearly outside the bulk
    # of the animal's own coat-colour distribution should.
    colour_thresh = float(np.percentile(colour_dist[mask_bool], 96))
    colour_thresh = max(colour_thresh, 45.0)  # floor so near-uniform coats don't flag everything
    colour_anomaly = ((colour_dist > colour_thresh) & mask_bool).astype(np.uint8) * 255
    # Require the anomaly to be a solid blob, not scattered single pixels /
    # thin edges (which is what leg/shadow boundaries typically look like).
    open_kernel = np.ones((5, 5), np.uint8)
    colour_anomaly = cv2.morphologyEx(colour_anomaly, cv2.MORPH_OPEN, open_kernel)

    # Local-texture anomaly, same technique as the crop lesion detector:
    # adaptive threshold picks out small dark/rough blobs (wounds, bald
    # patches, nodules) against the surrounding coat. A stronger blur and
    # larger block size avoid firing on ordinary fine coat texture / edges.
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray_masked = cv2.bitwise_and(gray, gray, mask=mask)
    blur = cv2.GaussianBlur(gray_masked, (7, 7), 0)
    texture_thresh = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 41, 10
    )
    texture_thresh = cv2.bitwise_and(texture_thresh, mask)
    texture_thresh = cv2.morphologyEx(texture_thresh, cv2.MORPH_OPEN, open_kernel)

    combined = cv2.bitwise_or(colour_anomaly, texture_thresh)
    kernel = np.ones((3, 3), np.uint8)
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = MIN_SKIN_PATCH_AREA_FRACTION * animal_area

    boxes = []
    patch_mask = np.zeros_like(mask)
    for c in contours:
        area = cv2.contourArea(c)
        if area >= min_area:
            boxes.append(cv2.boundingRect(c))
            cv2.drawContours(patch_mask, [c], -1, 255, -1)

    return patch_mask, boxes


def _extract_biomarkers(bgr: np.ndarray, frames_for_motion: Optional[List[np.ndarray]] = None
                         ) -> Tuple[LivestockBiomarkers, np.ndarray, Tuple[int, int, int, int], np.ndarray, list]:
    mask = largest_foreground_mask(bgr)
    bbox = largest_contour_bbox(mask)
    x, y, w, h = bbox

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask_bool = mask.astype(bool)
    if mask_bool.any():
        mean_hsv = tuple(float(v) for v in hsv[mask_bool].mean(axis=0))
    else:
        mean_hsv = (0.0, 0.0, 0.0)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    roughness_raw = float(np.abs(lap)[mask_bool].std()) if mask_bool.any() else 0.0
    # Normalise into a rough 0-100 band for display purposes. Divisor
    # calibrated against typical close-up animal-photo Laplacian-std values.
    coat_roughness = float(np.clip(roughness_raw / 200.0 * 100, 0, 100))

    frame_area = bgr.shape[0] * bgr.shape[1]
    body_area_pct = float(mask.sum() / 255) / frame_area * 100
    aspect_ratio = float(w) / h if h else 0.0

    patch_mask, patch_boxes = _skin_abnormality_patches(bgr, mask)
    animal_area = max(int(mask.sum() / 255), 1)
    patch_area_pct = float(patch_mask.sum() / 255) / animal_area * 100

    motion_score = None
    if frames_for_motion and len(frames_for_motion) >= 2:
        motion_score = _motion_magnitude(frames_for_motion)

    biomarkers = LivestockBiomarkers(
        coat_mean_hsv=mean_hsv,
        coat_texture_roughness=round(coat_roughness, 1),
        body_region_area_pct=round(body_area_pct, 1),
        aspect_ratio=round(aspect_ratio, 2),
        skin_patch_area_pct=round(patch_area_pct, 1),
        skin_patch_count=len(patch_boxes),
        motion_score=round(motion_score, 1) if motion_score is not None else None,
    )
    return biomarkers, mask, bbox, patch_mask, patch_boxes


def _motion_magnitude(frames: List[np.ndarray]) -> float:
    """Average dense-optical-flow magnitude between consecutive sampled frames,
    normalised to a 0-100 scale. A real, measurable quantity (not fabricated),
    used as an activity/movement proxy."""
    grays = [cv2.cvtColor(preprocess(f), cv2.COLOR_BGR2GRAY) for f in frames]
    mags = []
    for a, b in zip(grays, grays[1:]):
        flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        mags.append(float(mag.mean()))
    avg = float(np.mean(mags)) if mags else 0.0
    return float(np.clip(avg / 5.0 * 100, 0, 100))


def analyze_livestock_image(
    bgr: np.ndarray,
    animal_id: str,
    species: str,
    baseline: Optional[dict] = None,
    frames_for_motion: Optional[List[np.ndarray]] = None,
) -> LivestockAnalysisResult:
    """
    baseline: optional dict with this animal's historical mean/std for each
    biomarker (computed by src.database.db from past observations). If None,
    this is treated as the animal's first observation and only absolute
    (population-agnostic) heuristics are used.
    """
    img = preprocess(bgr)
    biomarkers, mask, bbox, patch_mask, patch_boxes = _extract_biomarkers(img, frames_for_motion)

    deviations: List[str] = []
    score = 0.0

    # --- Absolute heuristics (used regardless of history) -------------------
    # Low body-condition proxy: very small/large area relative to frame can
    # indicate framing issues OR a genuinely thin/bloated silhouette; we only
    # flag it as a *possible* indicator, clearly labelled as low-confidence.
    if biomarkers.body_region_area_pct < 15:
        score += 10
        deviations.append("animal occupies unusually little of the frame (re-check photo framing)")

    if biomarkers.coat_texture_roughness > 55:
        score += 20
        deviations.append("coat/skin texture shows higher-than-typical roughness")

    if biomarkers.skin_patch_count > 0:
        # Weight by how much of the body is affected, capped so a couple of
        # small patches don't alone push the animal straight to High Risk.
        patch_score = min(15 + biomarkers.skin_patch_area_pct * 2.0, 40)
        score += patch_score
        deviations.append(
            f"{biomarkers.skin_patch_count} localised skin/coat patch(es) detected "
            f"covering ~{biomarkers.skin_patch_area_pct}% of the visible body "
            f"({SKIN_PATCH_CONDITIONS_NOTE})"
        )

    if biomarkers.motion_score is not None and biomarkers.motion_score < 8:
        score += 20
        deviations.append("very low movement detected across sampled video frames")

    # --- Relative-to-baseline heuristics (only when history exists) ---------
    if baseline:
        hsv_now = np.array(biomarkers.coat_mean_hsv)
        hsv_base = np.array(baseline.get("coat_mean_hsv", hsv_now))
        hsv_delta = float(np.linalg.norm(hsv_now - hsv_base))
        if hsv_delta > 18:
            score += 20
            deviations.append("visual coat-colour biomarker changed notably vs. this animal's baseline")

        rough_base = baseline.get("coat_texture_roughness")
        if rough_base is not None and biomarkers.coat_texture_roughness - rough_base > 15:
            score += 15
            deviations.append("coat texture roughness increased vs. baseline")

        area_base = baseline.get("body_region_area_pct")
        if area_base is not None and abs(biomarkers.body_region_area_pct - area_base) > 12:
            score += 15
            deviations.append("body-condition-related visual footprint changed vs. baseline")

    score = float(np.clip(score, 0, 100))
    risk_level, emoji = _risk_level(score)

    indicators = [
        LivestockIndicator("Skin/coat patch abnormality",
                            biomarkers.skin_patch_count > 0,
                            f"{biomarkers.skin_patch_count} patch(es), "
                            f"~{biomarkers.skin_patch_area_pct}% of visible body — pattern only, "
                            f"not a named diagnosis ({SKIN_PATCH_CONDITIONS_NOTE})"
                            if biomarkers.skin_patch_count > 0
                            else "no localised skin/coat patches detected"),
        LivestockIndicator("Movement decreased",
                            biomarkers.motion_score is not None and biomarkers.motion_score < 8,
                            f"motion score {biomarkers.motion_score}" if biomarkers.motion_score is not None
                            else "no video provided — motion not assessed"),
        LivestockIndicator("Visual biomarker changed vs. baseline",
                            any("baseline" in d for d in deviations),
                            "coat colour/texture deviates from this animal's history" if baseline
                            else "no prior history yet for this animal"),
        LivestockIndicator("Body-condition indicator changed",
                            any("body-condition" in d for d in deviations),
                            "body-region visual footprint changed vs. baseline" if baseline
                            else "no prior history yet for this animal"),
    ]

    if risk_level == "Low Risk":
        recommendation = "No significant deviations detected. Continue routine observation."
    elif risk_level == "Moderate Risk":
        recommendation = "Monitor over the next few days and re-scan to confirm the trend."
    else:
        recommendation = "Monitor closely and consider a veterinary examination."

    if biomarkers.skin_patch_count > 0:
        recommendation += (
            " A localised skin/coat patch was flagged — have it physically examined; "
            "this system cannot tell a wound, parasite, ringworm/mange, or lumpy skin "
            "disease apart from a photo alone."
        )

    overlay = mask_overlay(img, mask, color=(0, 200, 255), alpha=0.20)
    overlay = draw_boxes(overlay, [bbox], color=(255, 0, 0), thickness=2, labels=["region of interest"])
    overlay = draw_boxes(overlay, patch_boxes, color=(0, 0, 255), thickness=2,
                         labels=["patch"] * len(patch_boxes))

    return LivestockAnalysisResult(
        animal_id=animal_id,
        species=species,
        risk_score=round(score, 1),
        risk_level=risk_level,
        risk_emoji=emoji,
        indicators=indicators,
        biomarkers=biomarkers,
        deviations=deviations,
        recommendation=recommendation,
        overlay_image=overlay,
        raw_metrics={
            "coat_mean_hsv": biomarkers.coat_mean_hsv,
            "coat_texture_roughness": biomarkers.coat_texture_roughness,
            "body_region_area_pct": biomarkers.body_region_area_pct,
            "aspect_ratio": biomarkers.aspect_ratio,
            "skin_patch_area_pct": biomarkers.skin_patch_area_pct,
            "skin_patch_count": biomarkers.skin_patch_count,
            "motion_score": biomarkers.motion_score,
        },
    )
