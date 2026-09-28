"""
Sowing-season reference data for the Planning Agent.

Same honesty caveat as backend/core/soil_config.py: these are broad,
commonly-cited sowing windows for major Indian cropping seasons
(Kharif/monsoon-sown, Rabi/winter-sown, and a few perennial/multi-season
cases) — NOT calibrated to any specific district's agro-climatic zone,
and not a substitute for a real regional crop-calendar data source (spec
section 20's Scheme/geospatial providers, not yet integrated). Months are
1-12, inclusive ranges, and deliberately wide rather than falsely precise.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SowingWindow:
    start_month: int
    end_month: int
    season_label: str

    def contains(self, month: int) -> bool:
        if self.start_month <= self.end_month:
            return self.start_month <= month <= self.end_month
        return month >= self.start_month or month <= self.end_month  # wraps around year-end


CROP_SOWING_WINDOWS: dict[str, list[SowingWindow]] = {
    "Tomato": [SowingWindow(6, 7, "Kharif nursery/transplant"), SowingWindow(10, 11, "Rabi")],
    "Potato": [SowingWindow(10, 11, "Rabi")],
    "Wheat": [SowingWindow(10, 12, "Rabi")],
    "Rice": [SowingWindow(6, 7, "Kharif")],
    "Maize/Corn": [SowingWindow(6, 7, "Kharif"), SowingWindow(1, 2, "Spring/Rabi")],
    "Cotton": [SowingWindow(4, 6, "Kharif, pre-monsoon")],
    "Sugarcane": [SowingWindow(2, 3, "Spring planting"), SowingWindow(9, 10, "Autumn planting")],
    "Chili": [SowingWindow(6, 7, "Kharif"), SowingWindow(11, 12, "Rabi")],
    "Grape": [SowingWindow(1, 2, "Pruning / new-season growth start (perennial crop)")],
}


def get_windows(crop_name: str) -> list[SowingWindow] | None:
    """Returns None (not an empty list) for a crop with no data on file —
    callers must treat that as 'no seasonal opinion', not 'sow anytime'."""
    return CROP_SOWING_WINDOWS.get(crop_name)


def nearest_window(crop_name: str, month: int) -> SowingWindow | None:
    windows = get_windows(crop_name)
    if not windows:
        return None
    def distance(w: SowingWindow) -> int:
        if w.contains(month):
            return 0
        forward = (w.start_month - month) % 12
        return forward
    return min(windows, key=distance)
