"""
Government scheme reference data for the Scheme Agent — spec section 8.

IMPORTANT CAVEAT: this is a small, curated snapshot of well-known central
government agricultural schemes as commonly documented, NOT a live feed
from data.gov.in or any government API, and NOT a complete list of
every central + state scheme a farmer might qualify for. Amounts,
eligibility rules, and application processes for real government schemes
change over time and vary by state. This module exists to demonstrate
real matching logic against real (if potentially dated) scheme
structures — not to be an authoritative source. Every SchemeAgent
recommendation says as much and points the farmer to verify locally
before treating this as final — see SchemeAgent's Recommendation
reasoning field.

A production deployment should replace this with a live connection to
a maintained government scheme database (spec section 20's "Scheme"
provider) rather than a hardcoded list like this one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SchemeCriteria:
    scheme_id: str
    name: str
    description: str
    benefit_summary: str
    max_land_acres: float | None       # None = no land-size limit
    eligible_categories: tuple[str, ...] | None  # None = open to all categories
    apply_via: str

    def matches(self, land_acres: float | None, category: str | None) -> bool:
        if self.max_land_acres is not None and land_acres is not None:
            if land_acres > self.max_land_acres:
                return False
        if self.eligible_categories is not None and category is not None:
            if category.lower() not in [c.lower() for c in self.eligible_categories]:
                return False
        return True


# Categories used below: "general", "small" (1-2 hectares / ~2.5-5 acres),
# "marginal" (<1 hectare / ~2.5 acres), "sc", "st", "woman" — a farmer may
# match more than one category; callers pass whichever applies most.
SCHEMES: list[SchemeCriteria] = [
    SchemeCriteria(
        scheme_id="pm_kisan",
        name="PM-KISAN (Pradhan Mantri Kisan Samman Nidhi)",
        description="Direct income support for landholding farmer families.",
        benefit_summary="\u20b96,000/year paid in three installments directly to the farmer's bank account "
                         "(figure as commonly documented — confirm the current amount at pmkisan.gov.in).",
        max_land_acres=None,
        eligible_categories=None,
        apply_via="pmkisan.gov.in, or your nearest Common Service Centre (CSC)",
    ),
    SchemeCriteria(
        scheme_id="pmfby",
        name="PMFBY (Pradhan Mantri Fasal Bima Yojana)",
        description="Crop insurance covering yield loss from natural calamities, pests, and disease.",
        benefit_summary="Low-premium crop insurance; payout depends on assessed crop loss.",
        max_land_acres=None,
        eligible_categories=None,
        apply_via="your bank branch, an empanelled insurance company, or the PMFBY portal — "
                  "enrollment has a season-specific cutoff date, so timing matters",
    ),
    SchemeCriteria(
        scheme_id="kcc",
        name="KCC (Kisan Credit Card)",
        description="Short-term credit access for cultivation and allied needs at subsidized interest.",
        benefit_summary="A credit line sized to your cropping pattern and land holding, at concessional interest rates.",
        max_land_acres=None,
        eligible_categories=None,
        apply_via="any nationalized or cooperative bank branch",
    ),
    SchemeCriteria(
        scheme_id="soil_health_card",
        name="Soil Health Card Scheme",
        description="Periodic free soil testing with fertilizer/nutrient recommendations.",
        benefit_summary="A soil health report roughly every 2-3 years, with crop-wise fertilizer guidance.",
        max_land_acres=None,
        eligible_categories=None,
        apply_via="your local Krishi Vigyan Kendra (KVK) or agriculture department office",
    ),
    SchemeCriteria(
        scheme_id="pmksy_micro_irrigation",
        name="PMKSY \u2014 Per Drop More Crop (micro-irrigation subsidy)",
        description="Subsidy toward drip/sprinkler irrigation equipment.",
        benefit_summary="Partial subsidy on approved micro-irrigation equipment cost — the exact percentage "
                         "varies by state and category, confirm locally.",
        max_land_acres=None,
        eligible_categories=None,
        apply_via="your state agriculture or horticulture department",
    ),
    SchemeCriteria(
        scheme_id="smam_sc_st_women",
        name="SMAM (Sub-Mission on Agricultural Mechanization) \u2014 enhanced subsidy tier",
        description="Additional subsidy on farm machinery for SC/ST/woman farmers, and small/marginal holdings.",
        benefit_summary="A higher subsidy percentage on approved farm equipment than the general tier "
                         "(exact rate varies by state and equipment — confirm locally).",
        max_land_acres=5.0,  # ~2 hectares, small/marginal holding
        eligible_categories=("sc", "st", "woman", "small", "marginal"),
        apply_via="your state agriculture department's mechanization scheme portal",
    ),
]
