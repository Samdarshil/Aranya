"""
Economics Agent — spec section 8.

Fully deterministic: sums this field's logged expenses and sales,
computes profit/margin, and produces a Recommendation. No LLM call, no
estimation of figures the farmer hasn't actually logged — this agent
reports on what was recorded, not a modeled guess (spec section 3: never
fabricate numbers).

Deliberately distinguishes three states, not just "profit" vs "loss":
  1. No data at all — nothing to report, says so honestly.
  2. Costs logged but no sales yet — mid-season is normal; reports
     spend-to-date without implying a loss, since the crop hasn't been
     sold.
  3. Both costs and sales logged — a real profit/loss figure.

Scoped to the field's current crop cycle (backend/memory/store.py's
get_active_cycle_expenses/get_active_cycle_sales), not the field's
all-time totals — replanting a field (Orchestrator.handle_start_new_crop_cycle)
starts a fresh cycle so last season's costs don't blend into this one's
profit/loss figure.
"""

from __future__ import annotations

from backend.agents.base import Agent, AgentContext, AgentError
from backend.core.schemas import Evidence, EvidenceSource, Recommendation, Severity, Urgency

# A loss beyond this fraction of total revenue is treated as significant
# enough to flag at MODERATE rather than LOW severity.
SIGNIFICANT_LOSS_MARGIN_PCT = -15.0


class EconomicsAgent(Agent):
    name = "economics_agent"

    def run(self, context: AgentContext, **kwargs) -> Recommendation:
        return self.compute_profitability(context, **kwargs)

    def compute_profitability(self, context: AgentContext, field_ref: str, crop_name: str) -> Recommendation:
        field_id = context.memory.get_or_create_field(context.farm_id, field_ref, crop_name)
        expenses = context.memory.get_active_cycle_expenses(field_id)
        sales = context.memory.get_active_cycle_sales(field_id)

        if not expenses and not sales:
            raise AgentError(
                f"No expenses or sales logged yet for field {field_ref} — nothing to report on.",
                retryable=True,
            )

        total_expenses = sum(e["amount"] for e in expenses)
        total_revenue = sum(s["quantity_kg"] * s["price_per_kg"] for s in sales)

        evidence = []
        if expenses:
            by_category: dict[str, float] = {}
            for e in expenses:
                by_category[e["category"]] = by_category.get(e["category"], 0.0) + e["amount"]
            breakdown = ", ".join(f"{cat}: \u20b9{amt:.0f}" for cat, amt in sorted(
                by_category.items(), key=lambda kv: -kv[1]
            ))
            evidence.append(Evidence(
                f"Total expenses logged: \u20b9{total_expenses:.0f} ({len(expenses)} entries) — {breakdown}",
                EvidenceSource.FARMER_REPORTED, confidence=0.8,
            ))
        if sales:
            total_kg = sum(s["quantity_kg"] for s in sales)
            evidence.append(Evidence(
                f"Total sales logged: \u20b9{total_revenue:.0f} for {total_kg:.0f}kg "
                f"({len(sales)} sale(s))",
                EvidenceSource.FARMER_REPORTED, confidence=0.8,
            ))

        if not sales:
            # Mid-season: costs only, nothing sold yet. Not a loss — just
            # spend-to-date. Reporting this as a "loss" would be actively
            # misleading (spec section 15: don't present uncertain/partial
            # data as more than it is).
            return Recommendation(
                problem=f"\u20b9{total_expenses:.0f} spent so far on field {field_ref} "
                        f"({crop_name}) — nothing sold yet",
                evidence=tuple(evidence),
                confidence=0.7,
                severity=Severity.INFO,
                urgency=Urgency.NONE,
                recommended_action="Log sales as they happen to see real profit/loss once harvest is sold.",
                reasoning="No sales are on record yet, so this is spend-to-date, not a profit/loss figure — "
                          "the crop hasn't been sold.",
                source_agent=self.name,
            )

        if not expenses:
            return Recommendation(
                problem=f"\u20b9{total_revenue:.0f} in sales logged for field {field_ref} "
                        f"({crop_name}) with no expenses on record",
                evidence=tuple(evidence),
                confidence=0.6,
                severity=Severity.INFO,
                urgency=Urgency.NONE,
                recommended_action="Log your costs (seed, fertilizer, labor, etc.) too, "
                                    "so profit can be calculated, not just revenue.",
                reasoning="Revenue is on record but no costs are, so profit can't be computed yet — "
                          "this total is revenue only.",
                source_agent=self.name,
            )

        profit = total_revenue - total_expenses
        margin_pct = (profit / total_revenue * 100) if total_revenue else 0.0
        evidence.append(Evidence(
            f"Profit: \u20b9{profit:.0f} ({margin_pct:+.1f}% margin)",
            EvidenceSource.FARM_MEMORY, confidence=0.9, raw_value=profit,
        ))

        if margin_pct <= SIGNIFICANT_LOSS_MARGIN_PCT:
            return Recommendation(
                problem=f"Field {field_ref} ({crop_name}) is running at a loss "
                        f"(\u20b9{profit:.0f}, {margin_pct:+.1f}% margin)",
                evidence=tuple(evidence),
                confidence=0.8,
                severity=Severity.MODERATE,
                urgency=Urgency.MONITOR,
                recommended_action="Review your largest expense category before the next cycle — "
                                    "see the expense breakdown above for where the spend concentrated.",
                reasoning="Recorded costs exceed recorded revenue by a significant margin.",
                source_agent=self.name,
            )

        return Recommendation(
            problem=f"Field {field_ref} ({crop_name}) profit: \u20b9{profit:.0f} "
                    f"({margin_pct:+.1f}% margin)",
            evidence=tuple(evidence),
            confidence=0.8,
            severity=Severity.INFO,
            urgency=Urgency.NONE,
            recommended_action="No action needed — this cycle is profitable based on what's logged.",
            reasoning="Recorded revenue exceeds recorded costs.",
            source_agent=self.name,
        )
