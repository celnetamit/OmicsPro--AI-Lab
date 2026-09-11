"""Commercial terms, configurable in admin (spec 12).

Spec 12: "Pricing, duration, run allowance and expiry must be configurable in
admin; do not hard-code commercial values in the scientific application."

The values below are only the defaults a fresh deployment starts from. The
figures that actually apply are read from ``admin_settings`` on every request,
so an administrator can change a price, a term or a run allowance without a
code release. What each tier *is* — its parameter scope, its export formats,
the features it carries — stays in the entitlement matrix, because that is the
product definition rather than a commercial number.
"""

from dataclasses import replace
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.constants import AccessTier
from app.core.entitlements import Allowance
from app.core.entitlements import allowance as base_allowance
from app.models import AdminSetting

CATALOGUE_KEY = "commercial.catalogue"
ALLOWANCE_KEY = "commercial.allowance"

#: Defaults only. Amounts are in minor currency units so no floating-point money
#: reaches the database. Basic is absent by design: it is never sold.
DEFAULT_CATALOGUE: Dict[str, dict] = {
    AccessTier.MODERATE.value: {"term_days": 90, "amount_minor_units": 499000, "currency": "INR"},
    AccessTier.EXPERT.value: {"term_days": 90, "amount_minor_units": 1299000, "currency": "INR"},
}


class CommercialConfigError(ValueError):
    """A proposed commercial configuration that would break the product."""


def _stored(db: Session, key: str) -> dict:
    setting = db.get(AdminSetting, key)
    return setting.value if setting and isinstance(setting.value, dict) else {}


# ------------------------------------------------------------------ pricing --
def catalogue(db: Session) -> Dict[AccessTier, dict]:
    """Price and term per purchasable tier, admin overrides applied."""
    stored = _stored(db, CATALOGUE_KEY)
    merged = {}
    for tier_value, default in DEFAULT_CATALOGUE.items():
        merged[AccessTier(tier_value)] = {**default, **(stored.get(tier_value) or {})}
    return merged


def validate_catalogue(value: dict) -> dict:
    """Reject a catalogue that could not be charged or would sell Basic."""
    if AccessTier.BASIC.value in value:
        raise CommercialConfigError(
            "Basic is included with flagship enrollment and is never sold, so it "
            "cannot have a price."
        )
    clean = {}
    for tier_value, terms in value.items():
        if tier_value not in DEFAULT_CATALOGUE:
            raise CommercialConfigError(f"'{tier_value}' is not a purchasable tier.")
        if not isinstance(terms, dict):
            raise CommercialConfigError(f"Terms for {tier_value} must be an object.")
        amount = terms.get("amount_minor_units", DEFAULT_CATALOGUE[tier_value]["amount_minor_units"])
        term = terms.get("term_days", DEFAULT_CATALOGUE[tier_value]["term_days"])
        currency = terms.get("currency", DEFAULT_CATALOGUE[tier_value]["currency"])
        if not isinstance(amount, int) or amount <= 0:
            raise CommercialConfigError(
                f"{tier_value}: the price must be a positive whole number of minor "
                f"units (for example 499000 for INR 4,990.00)."
            )
        if not isinstance(term, int) or not 1 <= term <= 3650:
            raise CommercialConfigError(f"{tier_value}: the term must be 1 to 3650 days.")
        if not (isinstance(currency, str) and len(currency) == 3 and currency.isalpha()):
            raise CommercialConfigError(f"{tier_value}: currency must be a 3-letter code.")
        clean[tier_value] = {
            "amount_minor_units": amount,
            "term_days": term,
            "currency": currency.upper(),
        }
    return clean


# ---------------------------------------------------------------- allowance --
def allowance_for(db: Session, tier: AccessTier) -> Allowance:
    """The tier's allowance with admin-configured run and perturbation limits."""
    base = base_allowance(tier)
    stored = (_stored(db, ALLOWANCE_KEY).get(tier.value) or {})
    overrides = {}
    if "runs_per_module_per_week" in stored:
        overrides["runs_per_module_per_week"] = stored["runs_per_module_per_week"]
    if "perturbations_per_run" in stored:
        overrides["perturbations_per_run"] = stored["perturbations_per_run"]
    return replace(base, **overrides) if overrides else base


def _rank_value(runs: Optional[int]) -> float:
    return float("inf") if runs is None else float(runs)


def validate_allowance(value: dict) -> dict:
    """Reject an allowance that would break the teaching core or invert tiers.

    Two rules protect the product. Basic must keep at least one run and one
    what-if test, because the spec's commercial safeguard says the promised
    learning is delivered at Basic. And a paid tier may not allow less than the
    tier below it, or the upgrade would take something away.
    """
    clean: Dict[str, dict] = {}
    for tier_value, limits in value.items():
        try:
            AccessTier(tier_value)
        except ValueError:
            raise CommercialConfigError(f"'{tier_value}' is not an access tier.")
        if not isinstance(limits, dict):
            raise CommercialConfigError(f"Limits for {tier_value} must be an object.")
        entry = {}
        if "runs_per_module_per_week" in limits:
            runs = limits["runs_per_module_per_week"]
            if runs is not None and (not isinstance(runs, int) or runs < 1 or runs > 10000):
                raise CommercialConfigError(
                    f"{tier_value}: runs per module per week must be 1 to 10000, or "
                    f"null for unmetered."
                )
            entry["runs_per_module_per_week"] = runs
        if "perturbations_per_run" in limits:
            perts = limits["perturbations_per_run"]
            if not isinstance(perts, int) or not 1 <= perts <= 100:
                raise CommercialConfigError(
                    f"{tier_value}: what-if tests per run must be 1 to 100."
                )
            entry["perturbations_per_run"] = perts
        clean[tier_value] = entry

    #: Check tier ordering against the effective values after the change.
    effective = {}
    for tier in AccessTier:
        base = base_allowance(tier)
        proposed = clean.get(tier.value, {})
        effective[tier] = (
            proposed.get("runs_per_module_per_week", base.runs_per_module_per_week),
            proposed.get("perturbations_per_run", base.perturbations_per_run),
        )
    order = [AccessTier.BASIC, AccessTier.MODERATE, AccessTier.EXPERT]
    for lower, higher in zip(order, order[1:]):
        if _rank_value(effective[higher][0]) < _rank_value(effective[lower][0]):
            raise CommercialConfigError(
                f"{higher.value.title()} would allow fewer runs than "
                f"{lower.value.title()}, so upgrading would take runs away."
            )
        if effective[higher][1] < effective[lower][1]:
            raise CommercialConfigError(
                f"{higher.value.title()} would allow fewer what-if tests than "
                f"{lower.value.title()}, so upgrading would take tests away."
            )
    return clean
