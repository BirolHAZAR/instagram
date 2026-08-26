from celery import shared_task
from django.utils import timezone
import logging

from core.services.analytics_sync_service import sync_ga4_property

logger = logging.getLogger(__name__)


def _normalize_analytics_code(platform):
    code = str(getattr(platform, "code", "") or "").lower().strip()
    name = str(getattr(platform, "name", "") or "").lower().strip()
    value = f"{code} {name}"

    if "analytics" in value or "ga4" in value or "google_analytics" in value:
        return "google_analytics"

    return code


def _get_analytics_api_class(platform_code):
    if platform_code == "google_analytics":
        from core.platforms.google_analytics import GoogleAnalyticsAPI
        return GoogleAnalyticsAPI

    return None


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_analytics_account(self, account_id):
    from core.models import PlatformAccount

    account = PlatformAccount.objects.select_related(
        "platform",
        "connection",
        "user",
    ).get(id=account_id, is_active=True)

    platform_code = _normalize_analytics_code(account.platform)
    api_class = _get_analytics_api_class(platform_code)

    if not api_class:
        raise Exception(f"Desteklenmeyen analytics platformu: {platform_code}")

    try:
        api = api_class(account)

        properties = api.get_properties()

        total_properties = 0
        total_daily_metrics = 0
        total_landing_pages = 0

        for property_payload in properties or []:
            property_id = property_payload.get("property_id")

            if not property_id:
                continue

            daily_metrics = api.get_daily_metrics(
                property_id=property_id,
                since_days=30,
            )

            landing_pages = api.get_landing_page_metrics(
                property_id=property_id,
                since_days=30,
            )

            sync_ga4_property(
                user=account.user,
                platform_account=account,
                property_payload=property_payload,
                daily_metrics=daily_metrics,
                landing_pages=landing_pages,
            )

            total_properties += 1
            total_daily_metrics += len(daily_metrics or [])
            total_landing_pages += len(landing_pages or [])

        account.last_sync = timezone.now()
        account.save(update_fields=["last_sync"])

        return {
            "account_id": account.id,
            "platform": platform_code,
            "properties": total_properties,
            "daily_metrics": total_daily_metrics,
            "landing_pages": total_landing_pages,
        }

    except Exception as exc:
        logger.exception("Analytics sync hatası account=%s", account_id)
        raise self.retry(exc=exc)


@shared_task
def sync_all_analytics_accounts():
    from core.models import PlatformAccount

    results = []

    accounts = PlatformAccount.objects.filter(
        is_active=True,
    ).select_related("platform", "connection", "user")

    for account in accounts:
        platform_code = _normalize_analytics_code(account.platform)

        if platform_code != "google_analytics":
            continue

        task = sync_analytics_account.delay(account.id)

        results.append({
            "account_id": account.id,
            "platform": platform_code,
            "task_id": task.id,
        })

    return results