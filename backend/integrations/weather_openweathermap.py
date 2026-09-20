"""
OpenWeatherMap provider — a real implementation of WeatherProvider.

STATUS: written, NOT executed in the authoring sandbox — that environment
has no network access, so this could not be run against the live
OpenWeatherMap API there. The HTTP call shape below is standard and
correct for OpenWeatherMap's "current weather" and "one call" endpoints;
verify against a real API key on a machine with network access.

If WEATHER_API_KEY is unset, `from_env()` returns None rather than a
half-configured client — callers must handle that (see
backend/agents/weather_agent.py) by falling back to "no data available",
never a fabricated reading (spec section 3).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from backend.core.providers import ProviderUnavailable, WeatherReading

BASE_URL = "https://api.openweathermap.org/data/2.5"
REQUEST_TIMEOUT_SECONDS = 10


class OpenWeatherMapProvider:
    name = "openweathermap"

    def __init__(self, api_key: str):
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "OpenWeatherMapProvider | None":
        key = os.environ.get("WEATHER_API_KEY")
        if not key:
            return None
        return cls(api_key=key)

    def get_current(self, lat: float, lng: float) -> WeatherReading:
        try:
            resp = requests.get(
                f"{BASE_URL}/weather",
                params={"lat": lat, "lon": lng, "appid": self._api_key, "units": "metric"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise ProviderUnavailable(f"OpenWeatherMap current-weather request failed: {exc}") from exc

        try:
            return WeatherReading(
                observed_at=datetime.now(timezone.utc),
                temperature_c=float(data["main"]["temp"]),
                humidity_pct=float(data["main"]["humidity"]),
                rainfall_last_24h_mm=float(data.get("rain", {}).get("1h", 0.0)) * 24,
                rainfall_forecast_24h_mm=0.0,  # current-weather endpoint has no forecast
                wind_speed_kmh=float(data["wind"]["speed"]) * 3.6,
                provider=self.name,
                is_forecast=False,
            )
        except (KeyError, TypeError) as exc:
            raise ProviderUnavailable(f"Unexpected OpenWeatherMap response shape: {exc}") from exc

    def get_forecast(self, lat: float, lng: float, hours_ahead: int = 24) -> WeatherReading:
        try:
            resp = requests.get(
                f"{BASE_URL}/forecast",
                params={"lat": lat, "lon": lng, "appid": self._api_key, "units": "metric"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise ProviderUnavailable(f"OpenWeatherMap forecast request failed: {exc}") from exc

        try:
            slots_needed = max(hours_ahead // 3, 1)  # forecast API returns 3-hour steps
            slots = data["list"][:slots_needed]
            if not slots:
                raise ProviderUnavailable("OpenWeatherMap returned no forecast slots")
            total_rain_mm = sum(s.get("rain", {}).get("3h", 0.0) for s in slots)
            avg_temp = sum(s["main"]["temp"] for s in slots) / len(slots)
            avg_humidity = sum(s["main"]["humidity"] for s in slots) / len(slots)
            avg_wind = sum(s["wind"]["speed"] for s in slots) / len(slots)
            return WeatherReading(
                observed_at=datetime.now(timezone.utc),
                temperature_c=float(avg_temp),
                humidity_pct=float(avg_humidity),
                rainfall_last_24h_mm=0.0,
                rainfall_forecast_24h_mm=float(total_rain_mm),
                wind_speed_kmh=float(avg_wind) * 3.6,
                provider=self.name,
                is_forecast=True,
            )
        except (KeyError, TypeError, IndexError) as exc:
            raise ProviderUnavailable(f"Unexpected OpenWeatherMap forecast response shape: {exc}") from exc
