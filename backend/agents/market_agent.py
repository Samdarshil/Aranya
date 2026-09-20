"""
Market Agent — spec sections 8, 20.

Fully deterministic: fetches today's price via MarketProvider, compares
it against this crop/market combination's own recent price history in
Farm Memory (not a generic "market is up" claim — specifically this
market's own trailing average), and produces a sell-now/hold/neutral
Recommendation. No LLM call.

Like WeatherAgent, the one rule enforced strictly (spec section 3): no
provider configured, or the provider fails, raises AgentError — never a
fabricated price. Unlike WeatherAgent, a single reading with no history
isn't itself an error: the agent still reports the price, just with an
explicit note that it can't judge a trend yet (spec section 15:
distinguish what's known from what isn't, rather than silently omitting
the caveat).
"""

from __future__ import annotations

from backend.agents.base import Agent, AgentContext, AgentError
from backend.core.providers import MarketProvider, MarketPriceReading, ProviderUnavailable
from backend.core.schemas import Evidence, EvidenceSource, Recommendation, Severity, Urgency

# A price move beyond this percentage from the trailing average is
# treated as significant enough to flag — conservative default, not
# calibrated to any specific crop's normal volatility.
SIGNIFICANT_MOVE_PCT = 8.0
MIN_HISTORY_FOR_TREND = 3


class MarketAgent(Agent):
    name = "market_agent"

    def __init__(self, provider: MarketProvider | None):
        self._provider = provider

    def run(self, context: AgentContext, **kwargs) -> Recommendation:
        return self.check_price(context, **kwargs)

    def check_price(self, context: AgentContext, crop_name: str, market_name: str) -> Recommendation:
        if self._provider is None:
            raise AgentError(
                "No market data provider is configured (MARKET_DATA_API_KEY unset). "
                "Price-based recommendations are unavailable — no price has been fabricated.",
                retryable=False,
            )
        try:
            reading = self._provider.get_latest_price(crop_name, market_name)
        except ProviderUnavailable as exc:
            raise AgentError(f"Market data provider unavailable: {exc}", retryable=True) from exc

        context.memory.get_or_create_market_watch(context.farm_id, crop_name, market_name)
        context.memory.save_market_price(
            crop_name=crop_name, market_name=market_name,
            price_per_quintal=reading.price_per_quintal, provider=reading.provider,
        )
        history = context.memory.get_market_price_history(crop_name, market_name, limit=30)

        rec = self._build_recommendation(reading, history)
        context.memory.log_event(
            context.farm_id, "market_check",
            f"{crop_name} at {market_name}: \u20b9{reading.price_per_quintal}/quintal",
        )
        return rec

    @staticmethod
    def _build_recommendation(reading: MarketPriceReading, history: list[dict]) -> Recommendation:
        evidence = [
            Evidence(
                description=f"Latest price for {reading.crop_name} at {reading.market_name}: "
                            f"\u20b9{reading.price_per_quintal}/quintal (source: {reading.provider})",
                source=EvidenceSource.EXTERNAL_PROVIDER, confidence=0.7,
                raw_value=reading.price_per_quintal,
            ),
        ]

        # history[0] is the reading we just saved; the rest is prior history.
        prior = history[1:]
        if len(prior) < MIN_HISTORY_FOR_TREND:
            evidence.append(Evidence(
                f"Only {len(prior)} prior price record(s) on file for this crop/market — "
                "not enough to judge a trend yet",
                EvidenceSource.FARM_MEMORY, confidence=1.0,
            ))
            return Recommendation(
                problem=f"Current {reading.crop_name} price at {reading.market_name}: "
                        f"\u20b9{reading.price_per_quintal}/quintal (no trend data yet)",
                evidence=tuple(evidence),
                confidence=0.5,
                severity=Severity.INFO,
                urgency=Urgency.NONE,
                recommended_action="Keep checking — price history will build up with each check, "
                                    "letting Aranya spot trends over time.",
                reasoning="Not enough price history for this crop/market combination to compare "
                          "today's price against.",
                source_agent=MarketAgent.name,
            )

        avg = sum(p["price_per_quintal"] for p in prior) / len(prior)
        pct_change = ((reading.price_per_quintal - avg) / avg) * 100 if avg else 0.0
        evidence.append(Evidence(
            f"Trailing average over last {len(prior)} recorded prices: \u20b9{avg:.0f}/quintal "
            f"({pct_change:+.1f}% vs today)",
            EvidenceSource.FARM_MEMORY, confidence=0.8,
        ))

        if pct_change >= SIGNIFICANT_MOVE_PCT:
            return Recommendation(
                problem=f"{reading.crop_name} price at {reading.market_name} is notably above "
                        f"its recent average ({pct_change:+.1f}%)",
                evidence=tuple(evidence),
                confidence=0.6,
                severity=Severity.LOW,
                urgency=Urgency.SOON,
                recommended_action="This may be a good window to sell if you have stock ready — "
                                    "prices above the recent average don't always hold.",
                reasoning="Price is meaningfully above its own recent trailing average for this "
                          "specific market, not a general market claim.",
                monitoring_plan="Re-check before committing to a sale — a single high reading "
                                 "isn't a guarantee the price stays up.",
                source_agent=MarketAgent.name,
            )
        if pct_change <= -SIGNIFICANT_MOVE_PCT:
            return Recommendation(
                problem=f"{reading.crop_name} price at {reading.market_name} is notably below "
                        f"its recent average ({pct_change:+.1f}%)",
                evidence=tuple(evidence),
                confidence=0.6,
                severity=Severity.LOW,
                urgency=Urgency.MONITOR,
                recommended_action="If you can afford to wait, holding off on selling may be "
                                    "worthwhile until the price recovers toward its recent average.",
                reasoning="Price is meaningfully below its own recent trailing average for this "
                          "specific market.",
                monitoring_plan="Re-check in a few days to see if the price recovers.",
                source_agent=MarketAgent.name,
            )

        return Recommendation(
            problem=f"{reading.crop_name} price at {reading.market_name} is close to its recent average",
            evidence=tuple(evidence),
            confidence=0.6,
            severity=Severity.INFO,
            urgency=Urgency.NONE,
            recommended_action="No strong signal either way — sell on your own timeline.",
            reasoning="Today's price is within normal range of its own recent trailing average.",
            source_agent=MarketAgent.name,
        )
