"""
Agmarknet provider — a real implementation of MarketProvider.

STATUS: written, NOT executed in the authoring sandbox — no network
access there to call the live data.gov.in Agmarknet resource API. The
request/response shape below matches data.gov.in's standard resource
API convention (api-key query param, filters[...] query params, JSON
records array); verify against a real API key on a machine with network
access, and expect to adjust field names — Agmarknet's resource schema
has changed over time and isn't guaranteed stable.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, time as datetime_time, timezone

import requests

from backend.core.providers import MarketPriceReading, ProviderUnavailable

# data.gov.in's "Variety-wise Daily Market Prices" resource. The resource
# ID is stable per-dataset on data.gov.in but is still worth re-verifying
# against the current catalog before relying on it in production.
BASE_URL = "https://api.data.gov.in/resource"
RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
REQUEST_TIMEOUT_SECONDS = 12
MAX_ATTEMPTS = 2
CACHE_SECONDS = 600
_price_cache: dict[tuple[str, str], tuple[float, MarketPriceReading]] = {}


class AgmarknetProvider:
    name = "agmarknet"

    def __init__(self, api_key: str):
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "AgmarknetProvider | None":
        key = os.environ.get("MARKET_DATA_API_KEY")
        if not key:
            return None
        return cls(api_key=key)

    def get_latest_price(self, crop_name: str, market_name: str) -> MarketPriceReading:
        cache_key = (crop_name.strip().casefold(), market_name.strip().casefold())
        cached = _price_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1]

        params = {
            "api-key": self._api_key,
            "format": "json",
            "limit": 1,
            "filters[commodity]": crop_name,
            "filters[market]": market_name,
        }
        last_error: requests.RequestException | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                resp = requests.get(
                    f"{BASE_URL}/{RESOURCE_ID}",
                    params=params,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt + 1 < MAX_ATTEMPTS:
                    # The public government API sometimes responds slowly.
                    # A single short retry stays within typical web request limits.
                    time.sleep(0.25)
            except requests.RequestException as exc:
                raise ProviderUnavailable(f"Agmarknet request failed: {exc}") from exc
        else:
            raise ProviderUnavailable(
                "Agmarknet did not respond after two attempts. Please try again shortly."
            ) from last_error

        records = data.get("records") or []
        if not records:
            raise ProviderUnavailable(
                f"No recent price data for {crop_name!r} at {market_name!r}."
            )

        try:
            record = records[0]
            # Agmarknet reports price per quintal in rupees; field name
            # varies by resource version — "modal_price" is the typical
            # (median/most common) traded price for the day.
            price = float(record["modal_price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable(f"Unexpected Agmarknet response shape: {exc}") from exc

        recorded_at = datetime.now(timezone.utc)
        date_text = record.get("arrival_date") or record.get("date")
        if date_text:
            for date_format in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    market_date = datetime.strptime(str(date_text), date_format).date()
                    recorded_at = datetime.combine(market_date, datetime_time.min, tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue

        reading = MarketPriceReading(
            crop_name=crop_name,
            market_name=market_name,
            price_per_quintal=price,
            recorded_at=recorded_at,
            provider=self.name,
        )
        _price_cache[cache_key] = (time.monotonic(), reading)
        return reading
