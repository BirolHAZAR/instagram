from celery import shared_task
from django.utils import timezone
import logging

from core.services.v2_ad_sync import upsert_v2_ad_snapshot

logger = logging.getLogger(__name__)


PLATFORM_ALIASES = {
    # Meta / Facebook / Instagram
    "meta": "facebook",
    "facebook": "facebook",
    "fb": "facebook",
    "instagram": "instagram",
    "ig": "instagram",

    # TikTok
    "tiktok": "tiktok",
    "tik_tok": "tiktok",
    "tik tok": "tiktok",

    # Google
    "google": "google_ads",
    "googleads": "google_ads",
    "google_ads": "google_ads",
    "google ads": "google_ads",
    "adwords": "google_ads",
    "analytics": "google_analytics",
    "ga4": "google_analytics",
    "google_analytics": "google_analytics",
    "google analytics": "google_analytics",
    "google analytics 4": "google_analytics",

    # LinkedIn
    "linkedin": "linkedin",
    "linked_in": "linkedin",
    "linked in": "linkedin",

    # X / Twitter
    "x": "x",
    "twitter": "x",

    # YouTube
    "youtube": "youtube",
    "you tube": "youtube",
}

SUPPORTED_AD_SYNC_PLATFORMS = {
    "facebook",
    "google_ads",
    "instagram",
    "linkedin",
    "tiktok",
    "x",
    "youtube",
}


def normalize_platform_code(platform):
    """Platform.code veya Platform.name alanından standart servis kodu üretir."""
    code = getattr(platform, "code", "") or ""
    name = getattr(platform, "name", "") or ""

    raw_values = [code, name]

    for raw in raw_values:
        key = str(raw or "").strip().lower()
        if not key:
            continue

        normalized_key = (
            key.replace("-", "_")
            .replace(".", "_")
            .replace("/", "_")
        )

        if key in PLATFORM_ALIASES:
            return PLATFORM_ALIASES[key]

        if normalized_key in PLATFORM_ALIASES:
            return PLATFORM_ALIASES[normalized_key]

        compact_key = normalized_key.replace("_", "")
        if compact_key in PLATFORM_ALIASES:
            return PLATFORM_ALIASES[compact_key]

    return str(code or name or "").strip().lower()


def _get_api_class(platform_code):
    if platform_code == "facebook":
        from core.platforms.facebook import FacebookAPI
        return FacebookAPI
    if platform_code == "tiktok":
        from core.platforms.tiktok import TikTokAPI
        return TikTokAPI
    if platform_code == "google_ads":
        from core.platforms.google_ads import GoogleAdsAPI
        return GoogleAdsAPI
    if platform_code == "linkedin":
        from core.platforms.linkedin import LinkedInAPI
        return LinkedInAPI
    if platform_code == "x":
        from core.platforms.x import XAPI
        return XAPI
    if platform_code == "youtube":
        from core.platforms.youtube import YouTubeAPI
        return YouTubeAPI
    return None


def _get_account_token(account):
    connection = getattr(account, "connection", None)
    return getattr(account, "access_token", None) or getattr(connection, "access_token", None) or ""


def _is_placeholder_token(token):
    token = str(token or "").strip().lower()
    return (
        not token
        or token in {"test", "token", "em", "none", "null"}
        or len(token) < 20
    )


def _should_skip_ad_sync(account, platform_code):
    if platform_code not in SUPPORTED_AD_SYNC_PLATFORMS:
        return "unsupported_for_ad_sync"

    if (getattr(account, "extra_data", None) or {}).get("demo"):
        return "demo_account"

    if platform_code == "instagram":
        if _is_placeholder_token(_get_account_token(account)):
            return "missing_or_placeholder_token"

    return None


def _skip_result(account, platform_code, source_type, reason, failed=False, error=None):
    result = {
        "account_id": account.id,
        "platform": platform_code,
        "source_type": source_type,
        "ads_synced": 0,
        "skipped": True,
        "reason": reason,
    }
    if failed:
        result["failed"] = True
    if error:
        result["error"] = str(error)
    return result


def _is_non_retryable_api_error(response):
    status_code = response.get("status_code") if isinstance(response, dict) else None
    return status_code in {400, 401, 403, 404}


def _normalize_item(platform_code, item):
    item = dict(item or {})

    item.setdefault("platform_ad_id", item.get("ad_id") or item.get("id"))
    item.setdefault("platform_campaign_id", item.get("campaign_id") or f"{platform_code}-default-campaign")
    item.setdefault("campaign_name", item.get("campaign_name") or "Varsayılan Kampanya")
    item.setdefault(
        "platform_adgroup_id",
        item.get("adset_id") or item.get("adgroup_id") or f"{item['platform_campaign_id']}-default-adgroup",
    )
    item.setdefault("adgroup_name", item.get("adset_name") or item.get("adgroup_name") or "Varsayılan Reklam Grubu")
    item.setdefault("date", timezone.now().date().isoformat())

    return item


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_v2_platform_account_ads(self, account_id, source_type="OWN", days_back=None):
    from core.models import PlatformAccount
    from core.services.sync_policy import policy_for_user

    account = PlatformAccount.objects.select_related("platform", "connection", "user").get(
        id=account_id,
        is_active=True,
    )

    platform_code = normalize_platform_code(account.platform)
    source_type = (source_type or "OWN").upper()
    policy = policy_for_user(account.user)
    if not policy:
        return _skip_result(account, platform_code, source_type, "active_subscription_required")
    days_back = int(days_back or policy.history_days)

    skip_reason = _should_skip_ad_sync(account, platform_code)
    if skip_reason:
        logger.info(
            "V2 ad sync skipped account=%s platform=%s reason=%s",
            account_id,
            platform_code,
            skip_reason,
        )
        return _skip_result(account, platform_code, source_type, skip_reason)

    try:
        if platform_code == "instagram":
            from core.instagram_api import InstagramAPI

            token = _get_account_token(account)
            api = InstagramAPI(access_token=token)
            response = api.get_ads_insights(account.account_id, since_days=days_back)

            if isinstance(response, dict) and response.get("error"):
                if _is_non_retryable_api_error(response):
                    logger.warning(
                        "V2 ad sync non-retryable API error account=%s platform=%s status=%s error=%s",
                        account_id,
                        platform_code,
                        response.get("status_code"),
                        response.get("error"),
                    )
                    return _skip_result(
                        account,
                        platform_code,
                        source_type,
                        "non_retryable_api_error",
                        failed=True,
                        error=response.get("error"),
                    )
                raise Exception(response["error"])

            ads_data = response.get("data", []) if isinstance(response, dict) else response
        else:
            api_class = _get_api_class(platform_code)
            if not api_class:
                raise Exception(
                    f"Desteklenmeyen platform: code={getattr(account.platform, 'code', '')}, "
                    f"name={getattr(account.platform, 'name', '')}, normalized={platform_code}"
                )

            api = api_class(account)
            ads_data = api.get_ads()

        created_or_updated = 0

        for item in (ads_data or [])[:policy.max_records]:
            item = _normalize_item(platform_code, item)
            upsert_v2_ad_snapshot(
                user=account.user,
                platform_account=account,
                payload=item,
                source_type=source_type,
            )
            created_or_updated += 1

        account.last_sync = timezone.now()
        account.save(update_fields=["last_sync"])

        # Reklamlar ve metrikler veritabanına yazıldıktan sonra kural motoru
        # yalnız ilgili hesap için otomatik çalışır. Kuyruk geçici olarak kapalıysa
        # periyodik güvenlik taraması aynı kullanıcıyı daha sonra yeniden yakalar.
        rule_engine_task_id = None
        try:
            from core.tasks.admin_ops import generate_octo_tasks

            rule_engine_task = generate_octo_tasks.apply_async(
                kwargs={
                    "user_id": account.user_id,
                    "account_id": account.id,
                    "trigger": "ad_sync",
                    "days": min(max(days_back, 7), 30),
                },
                countdown=5,
                queue="ai",
            )
            rule_engine_task_id = rule_engine_task.id
        except Exception:
            logger.exception("Octo kural motoru kuyruğa alınamadı account=%s", account.id)

        return {
            "account_id": account.id,
            "platform": platform_code,
            "source_type": source_type,
            "ads_synced": created_or_updated,
            "rule_engine": {
                "status": "queued" if rule_engine_task_id else "periodic_fallback",
                "task_id": rule_engine_task_id,
            },
        }

    except Exception as exc:
        logger.exception("V2 sync hatası account=%s platform=%s", account_id, platform_code)
        raise self.retry(exc=exc)


@shared_task
def sync_all_v2_platform_accounts():
    from core.models import PlatformAccount
    from core.services.sync_policy import acquire_sync_lock, is_sync_due

    results = []

    for account in PlatformAccount.objects.filter(is_active=True).select_related("platform", "connection"):
        if not is_sync_due(account.user, account.last_sync, kind="ad"):
            continue
        lock_key, acquired = acquire_sync_lock("platform-dispatch", account.id, timeout=1800)
        if not acquired:
            continue
        platform_code = normalize_platform_code(account.platform)
        skip_reason = _should_skip_ad_sync(account, platform_code)
        if skip_reason:
            results.append(_skip_result(account, platform_code, "OWN", skip_reason))
            continue
        task = sync_v2_platform_account_ads.delay(account.id, "OWN")
        results.append({
            "account_id": account.id,
            "platform": platform_code,
            "task_id": task.id,
        })

    return results
