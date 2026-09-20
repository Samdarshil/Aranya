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
from datetime import datetime, timezone

import requests

from backend.core.providers import MarketPriceReading, ProviderUnavailable

# data.gov.in's "Variety-wise Daily Market Prices" resource. The resource
# ID is stable per-dataset on data.gov.in but is still worth re-verifying
# against the current catalog before relying on it in production.
BASE_URL = "https://api.data.gov.in/resource"
RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
REQUEST_TIMEOUT_SECONDS = 10


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
        try:
            resp = requests.get(
                f"{BASE_URL}/{RESOURCE_ID}",
                params={
                    "api-key": self._api_key,
                    "format": "json",
                    "limit": 1,
                    "filters[commodity]": crop_name,
                    "filters[market]": market_name,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise ProviderUnavailable(f"Agmarknet request failed: {exc}") from exc

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

        return MarketPriceReading(
            crop_name=crop_name,
            market_name=market_name,
            price_per_quintal=price,
            recorded_at=datetime.now(timezone.utc),
            provider=self.name,
        )
