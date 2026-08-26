from django.core.cache import cache
from django.db import transaction

from core.services.cache_service import CacheService


USER_NAMESPACES = (
    "dashboard", "control_tower", "reports_center", "health_center",
    "ads_panel_accounts", "campaign_panel_accounts", "competitors",
    "competitor_movements", "competitor_movements_page", "competitor_intelligence",
    "performance_center", "ai_dashboard", "organic_content", "daily_budget_report", "report_history",
    "ad_comparison",
)


def related_user_ids(instance):
    ids = set()
    user_id = getattr(instance, "user_id", None)
    if user_id:
        ids.add(user_id)
    account = getattr(instance, "platform_account", None)
    if account is None:
        account = getattr(getattr(instance, "ad", None), "platform_account", None)
    if account is None:
        account = getattr(getattr(instance, "campaign", None), "platform_account", None)
    if account is None:
        account = getattr(getattr(instance, "reklam", None), "platform_account", None)
    if account is not None:
        if account.user_id:
            ids.add(account.user_id)
        client = getattr(account, "agency_client", None)
        if client is not None:
            organization = client.organization
            ids.add(organization.owner_id)
            ids.update(organization.members.filter(is_active=True).values_list("user_id", flat=True))
    client = getattr(instance, "agency_client", None)
    if client is not None:
        organization = client.organization
        ids.add(organization.owner_id)
        ids.update(organization.members.filter(is_active=True).values_list("user_id", flat=True))
    social_post = getattr(instance, "social_post", None)
    if social_post is not None and social_post.user_id:
        ids.add(social_post.user_id)
    return {value for value in ids if value}


def schedule_instance_cache_invalidation(sender, instance, **kwargs):
    user_ids = related_user_ids(instance)
    account_id = (
        getattr(instance, "platform_account_id", None)
        or getattr(getattr(instance, "ad", None), "platform_account_id", None)
        or getattr(getattr(instance, "campaign", None), "platform_account_id", None)
        or getattr(getattr(instance, "reklam", None), "platform_account_id", None)
    )
    client = getattr(instance, "agency_client", None) or getattr(getattr(instance, "platform_account", None), "agency_client", None)
    organization_id = getattr(client, "organization_id", None)
    for user_id in user_ids:
        guard = CacheService.make_key("invalidate_guard", "user", user_id)
        if not cache.add(guard, 1, timeout=2):
            continue

        def invalidate(uid=user_id, aid=account_id, oid=organization_id):
            for namespace in USER_NAMESPACES:
                CacheService.bump_version(namespace, uid)
            if aid:
                CacheService.bump_version("ads_panel_account", uid, aid)
                CacheService.bump_version("campaign_panel_account", uid, aid)
            if oid:
                CacheService.bump_version("agency_dashboard", oid)

        transaction.on_commit(invalidate)
