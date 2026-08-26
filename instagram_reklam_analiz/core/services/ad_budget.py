from decimal import Decimal, InvalidOperation


def _decimal(value):
    try:
        if value in (None, ""):
            return Decimal("0")
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def current_budget_for_ad(ad):
    """Return the canonical budget stored for an ad.

    Platforms normally own budget at ad-group/ad-set level. Campaign budget is
    used when no ad-group budget exists. Lifetime budget is only a final fallback.
    """
    ad_group = getattr(ad, "ad_group", None)
    campaign = getattr(ad, "campaign", None)

    for owner, field, budget_type in (
        (ad_group, "daily_budget", "daily"),
        (campaign, "daily_budget", "daily"),
        (ad_group, "lifetime_budget", "lifetime"),
        (campaign, "lifetime_budget", "lifetime"),
    ):
        if owner is None:
            continue
        value = _decimal(getattr(owner, field, None))
        if value > 0:
            return value, budget_type

    return Decimal("0"), "unavailable"
