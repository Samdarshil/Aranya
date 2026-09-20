"""
External data provider abstraction — spec section 20.

"Do not hardwire business logic to a single provider." Every external
data source (weather, market, schemes, ...) is accessed through a small
Protocol like WeatherProvider below, so swapping vendors or adding a
second one for redundancy never touches agent code.

Equally important per spec section 3: if no provider is configured (no
API key set), the correct behaviour is to say so and refuse to guess —
never fabricate a plausible-looking reading.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ProviderUnavailable(Exception):
    """Raised when a provider cannot supply data — missing API key,
    network failure, or the provider explicitly has nothing for the
    requested location/time. Callers must treat this as 'no data', never
    catch-and-fabricate."""


@dataclass(frozen=True)
class WeatherReading:
    observed_at: datetime
    temperature_c: float
    humidity_pct: float
    rainfall_last_24h_mm: float
    rainfall_forecast_24h_mm: float
    wind_speed_kmh: float
    provider: str
    is_forecast: bool = False


class WeatherProvider(Protocol):
    """Any weather data source implements this. See
    backend/integrations/weather_openweathermap.py for a real
    implementation (requires an API key and network access — neither is
    available in the sandbox this was authored in, so it is written but
    unexecuted; see docs/STATUS.md)."""

    name: str

    def get_current(self, lat: float, lng: float) -> WeatherReading:
        """Raises ProviderUnavailable if no reading can be obtained."""
        ...

    def get_forecast(self, lat: float, lng: float, hours_ahead: int = 24) -> WeatherReading:
        """Raises ProviderUnavailable if no forecast can be obtained."""
        ...


@dataclass(frozen=True)
class MarketPriceReading:
    crop_name: str
    market_name: str
    price_per_quintal: float
    recorded_at: datetime
    provider: str


class MarketProvider(Protocol):
    """Any mandi/market price data source implements this. See
    backend/integrations/market_agmarknet.py for a real implementation
    (requires network access to India's Agmarknet/data.gov.in APIs,
    unavailable in the authoring sandbox — written but unexecuted; see
    docs/STATUS.md)."""

    name: str

    def get_latest_price(self, crop_name: str, market_name: str) -> MarketPriceReading:
        """Raises ProviderUnavailable if no price can be obtained for
        this crop/market combination."""
        ...
