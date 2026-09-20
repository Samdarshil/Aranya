"""
Image quality/validation gate — spec section 11 ("Image Quality Check"
is the first step in the vision pipeline diagram) and spec section 19
("file validation").

Runs before ANY CV processing — catches malformed arrays, too-small
images, absurdly large ones (a basic DoS/resource-abuse guard), and
degenerate blank/solid-color frames (a common accidental-upload case:
photographing a dark pocket, a blank wall, or a failed camera capture).
This is deliberately cheap (no OpenCV calls) so a bad upload fails fast
rather than wasting time in the segmentation/analysis pipeline first.

Note: the crop pipeline separately has its OWN quality signal
(leaf_area_pct_of_frame — "is there actually a plant in frame") which
this does NOT replace; that check needs actual segmentation, so it stays
where it is, later in the pipeline. This module catches the cases that
would break segmentation entirely, before it's even attempted.
"""

from __future__ import annotations

import numpy as np

MIN_DIMENSION_PX = 64
MAX_DIMENSION_PX = 8000
# Standard deviation of pixel values below this is treated as "blank" —
# a real photo (even a close-up of a single leaf) has far more variance
# than this; a genuinely solid-color or corrupt frame does not.
MIN_PIXEL_STDDEV = 3.0


class ImageValidationError(Exception):
    """Raised for any image that shouldn't proceed to CV analysis.
    Message is written to be shown directly to the farmer."""


def validate_image(bgr: np.ndarray) -> None:
    """Raises ImageValidationError if `bgr` isn't a usable image. Returns
    None (no exception) if it passes — callers proceed with analysis."""
    if bgr is None:
        raise ImageValidationError("No image was received.")

    if not isinstance(bgr, np.ndarray):
        raise ImageValidationError(f"Expected an image array, got {type(bgr).__name__}.")

    if bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ImageValidationError(
            "Image isn't in the expected 3-channel color format — it may be corrupted "
            "or in an unsupported mode (e.g. grayscale or with a transparency channel "
            "that wasn't flattened). Try re-taking the photo."
        )

    height, width = bgr.shape[:2]
    if height < MIN_DIMENSION_PX or width < MIN_DIMENSION_PX:
        raise ImageValidationError(
            f"Image is too small ({width}x{height}px) to analyze reliably — "
            f"please use a photo at least {MIN_DIMENSION_PX}x{MIN_DIMENSION_PX}px."
        )

    if height > MAX_DIMENSION_PX or width > MAX_DIMENSION_PX:
        raise ImageValidationError(
            f"Image is unusually large ({width}x{height}px) — please use a "
            f"standard photo, not a raw/panoramic/scan file."
        )

    if float(np.std(bgr)) < MIN_PIXEL_STDDEV:
        raise ImageValidationError(
            "This image appears to be blank or a single solid color — it doesn't look "
            "like a real photo. Please check the camera and try again."
        )
