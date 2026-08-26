from dataclasses import dataclass
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.services.agency_permission_matrix import get_user_entitlement_plan


@dataclass(frozen=True)
class SyncPolicy:
    ad_interval_minutes: int
    competitor_interval_minutes: int
    organic_interval_minutes: int
    marketplace_interval_minutes: int
    history_days: int
    max_records: int
    plan_name: str = ""

    @property
    def interval_hours(self):
        """Backward-compatible display value for advertisement sync."""
        return self.ad_interval_minutes / 60

    def interval_minutes_for(self, kind):
        return {
            "ad": self.ad_interval_minutes,
            "competitor": self.competitor_interval_minutes,
            "organic": self.organic_interval_minutes,
            "marketplace": self.marketplace_interval_minutes,
        }.get(kind, self.ad_interval_minutes)


def policy_for_user(user):
    plan = get_user_entitlement_plan(user)
    if not plan:
        return None
    return SyncPolicy(
        max(1, int(plan.ad_sync_interval_minutes or 1)),
        max(1, int(plan.competitor_sync_interval_minutes or 1)),
        max(1, int(plan.organic_sync_interval_minutes or 1)),
        max(1, int(plan.marketplace_sync_interval_minutes or 1)),
        max(1, int(plan.content_fetch_period_days or 30)),
        max(1, int(plan.max_sync_records or 1)),
        plan.name,
    )


def normalize_sync_time(value):
    if isinstance(value, str):
        value = parse_datetime(value)
    if value and timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value


def is_sync_due(user, last_sync, now=None, kind="ad"):
    policy = policy_for_user(user)
    if not policy:
        return False
    last_sync = normalize_sync_time(last_sync)
    return not last_sync or (now or timezone.now()) >= last_sync + timedelta(
        minutes=policy.interval_minutes_for(kind)
    )


def manual_sync_allowed(user, kind):
    plan = get_user_entitlement_plan(user)
    if not plan:
        return False
    field = {
        "ad": "allow_manual_ad_sync",
        "competitor": "allow_manual_competitor_sync",
        "organic": "allow_manual_organic_sync",
        "marketplace": "allow_manual_marketplace_sync",
    }.get(kind)
    return bool(field and getattr(plan, field, False))


def acquire_sync_lock(kind, object_id, timeout=3600):
    key = f"sync-lock:{kind}:{object_id}"
    return key, cache.add(key, timezone.now().isoformat(), timeout=timeout)


def release_sync_lock(key):
    cache.delete(key)
