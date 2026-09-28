"""
Soil tolerance reference data for the Soil Agent.

These are general, widely-cited agronomic ranges for common crops — NOT
variety-specific, NOT regional-soil-survey-calibrated, and not a
substitute for a real regional agricultural extension recommendation.
Labeled explicitly so nobody mistakes this for authoritative regional
agronomy data. A real deployment should let a regional agricultural
department override these per-region (see docs/STATUS.md).

Nitrogen/Phosphorus/Potassium bands are in ppm from a standard soil
test, split into low / sufficient / high. "Low" triggers a
fertilization recommendation; "high" triggers an over-fertilization
caution (excess nutrients can pollute runoff and doesn't help yield).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CropSoilProfile:
    ph_min: float
    ph_max: float
    nitrogen_low_ppm: float
    nitrogen_high_ppm: float
    phosphorus_low_ppm: float
    phosphorus_high_ppm: float
    potassium_low_ppm: float
    potassium_high_ppm: float


# Generic reference ranges — see module docstring caveat above.
CROP_SOIL_PROFILES: dict[str, CropSoilProfile] = {
    "Tomato": CropSoilProfile(6.0, 6.8, 20, 60, 15, 50, 100, 300),
    "Potato": CropSoilProfile(5.0, 6.0, 20, 60, 15, 50, 100, 300),
    "Wheat": CropSoilProfile(6.0, 7.5, 20, 50, 10, 40, 100, 250),
    "Rice": CropSoilProfile(5.5, 6.5, 20, 50, 10, 40, 80, 250),
    "Maize/Corn": CropSoilProfile(5.8, 7.0, 25, 60, 15, 45, 100, 280),
    "Cotton": CropSoilProfile(5.8, 8.0, 20, 55, 12, 45, 100, 280),
    "Sugarcane": CropSoilProfile(6.0, 7.5, 25, 65, 15, 50, 120, 320),
    "Chili": CropSoilProfile(6.0, 7.0, 20, 55, 15, 50, 100, 300),
    "Grape": CropSoilProfile(5.5, 7.0, 15, 45, 10, 40, 100, 280),
}

# Generic fallback when a crop isn't in the table above — wide, neutral
# range so the agent degrades to "no strong opinion" rather than
# fabricating crop-specific numbers it doesn't have.
DEFAULT_PROFILE = CropSoilProfile(6.0, 7.0, 20, 55, 15, 45, 100, 280)


def get_profile(crop_name: str) -> CropSoilProfile:
    return CROP_SOIL_PROFILES.get(crop_name, DEFAULT_PROFILE)
