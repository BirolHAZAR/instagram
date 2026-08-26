from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from core.models import PlatformConnection, SystemErrorLog
from core.services.notification_helper import NotificationHelper


REFRESH_WINDOW = timedelta(days=7)
HEALTH_CACHE_KEY = "platform_token_health:latest"
ENV_FAILURE_DEDUPE_WINDOW = timedelta(hours=6)

logger = logging.getLogger(__name__)


def _safe_error(exc, token=""):
    text = str(exc or "")
    return text.replace(str(token), "[ACCESS_TOKEN]")[:500] if token else text[:500]


def _expiry_from_timestamp(value):
    try:
        timestamp = int(value or 0)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, tz=dt_timezone.utc) if timestamp > 0 else None


def _debug_meta_token(token, platform_code):
    if platform_code == "instagram":
        app_id, app_secret = settings.INSTAGRAM_APP_ID, settings.INSTAGRAM_APP_SECRET
    else:
        app_id, app_secret = settings.FACEBOOK_APP_ID, settings.FACEBOOK_APP_SECRET
    response = requests.get(
        f"{settings.FACEBOOK_GRAPH_URL}/debug_token",
        params={"input_token": token, "access_token": f"{app_id}|{app_secret}"},
        timeout=30,
    )
    payload = response.json()
    if not response.ok or payload.get("error"):
        error = payload.get("error") or {}
        raise RuntimeError(error.get("message") or "Meta token kontrolü tamamlanamadı.")
    data = payload.get("data") or {}
    return {
        "valid": bool(data.get("is_valid")),
        "expires_at": _expiry_from_timestamp(data.get("expires_at")),
        "data_access_expires_at": _expiry_from_timestamp(data.get("data_access_expires_at")),
    }


def _refresh_instagram_token(token):
    if str(token).startswith("IG"):
        response = requests.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": token},
            timeout=30,
        )
    else:
        response = requests.get(
            f"{settings.FACEBOOK_GRAPH_URL}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.INSTAGRAM_APP_ID,
                "client_secret": settings.INSTAGRAM_APP_SECRET,
                "fb_exchange_token": token,
            },
            timeout=30,
        )
    payload = response.json()
    if not response.ok or payload.get("error"):
        error = payload.get("error") or {}
        raise RuntimeError(error.get("message") or "Instagram tokenı yenilenemedi.")
    return payload.get("access_token") or "", int(payload.get("expires_in") or 0)


def _validate_connection(connection):
    token = connection.access_token or ""
    if not token:
        return {"valid": False, "error": "Access token yok."}
    if (connection.extra_data or {}).get("demo"):
        return {"valid": True, "expires_at": connection.token_expiry, "validation": "demo"}
    if connection.platform.code in {"instagram", "facebook"}:
        try:
            return _debug_meta_token(token, connection.platform.code)
        except Exception:
            # Token başka bir Meta uygulaması tarafından üretildiyse debug_token
            # reddedilebilir. Bu durumda gerçek, salt-okunur uç noktayı prob et.
            if connection.platform.code == "instagram":
                instagram_id = (connection.extra_data or {}).get("instagram_business_account_id")
                url = f"{settings.FACEBOOK_GRAPH_URL}/{instagram_id}" if instagram_id else f"{settings.FACEBOOK_GRAPH_URL}/me/accounts"
                params = {"fields": "id,username" if instagram_id else "id", "access_token": token}
            else:
                url = f"{settings.FACEBOOK_GRAPH_URL}/me"
                params = {"fields": "id,name", "access_token": token}
            response = requests.get(url, params=params, timeout=30)
            if response.ok:
                return {"valid": True, "expires_at": connection.token_expiry, "validation": "live_probe"}
            payload = response.json()
            error = payload.get("error") or {}
            if error.get("code") == 190:
                return {"valid": False, "expires_at": connection.token_expiry}
            raise RuntimeError(error.get("message") or "Meta token canlı kontrolü tamamlanamadı.")
    if connection.platform.code in {"youtube", "tiktok", "linkedin", "x"}:
        from core.views.hesap_ekle import _resolve_token_platform_accounts

        try:
            accounts = _resolve_token_platform_accounts(connection.platform.code, token)
            return {"valid": bool(accounts), "expires_at": connection.token_expiry, "validation": "live_probe"}
        except ValueError:
            return {"valid": False, "expires_at": connection.token_expiry}
    return {"valid": not connection.is_token_expired, "expires_at": connection.token_expiry}


def _notify_connection_issue(connection, message, *, critical=False):
    NotificationHelper.notify(
        connection.user,
        "Platform tokenı geçersiz" if critical else "Platform token kontrolü başarısız",
        f"{connection.platform.name} - {connection.name or 'bağlantı'}: {message}"[:300],
        "critical" if critical else "warning",
        "🚨" if critical else "⚠️",
        "/platform-connections/",
        dedupe_minutes=720 if critical else 180,
    )


def _validate_env_instagram_token(token):
    response = requests.get(
        f"{settings.FACEBOOK_GRAPH_URL}/me/accounts",
        params={"fields": "id,instagram_business_account{id,username}", "access_token": token},
        timeout=30,
    )
    payload = response.json()
    accounts = payload.get("data") or []
    instagram_accounts = [row.get("instagram_business_account") for row in accounts if row.get("instagram_business_account")]
    permissions_response = requests.get(
        f"{settings.FACEBOOK_GRAPH_URL}/me/permissions",
        params={"access_token": token},
        timeout=30,
    )
    permissions_payload = permissions_response.json()
    granted = {
        row.get("permission") for row in permissions_payload.get("data", [])
        if row.get("status") == "granted"
    }
    ad_accounts_response = requests.get(
        f"{settings.FACEBOOK_GRAPH_URL}/me/adaccounts",
        params={"fields": "id", "access_token": token},
        timeout=30,
    )
    ad_accounts_payload = ad_accounts_response.json()
    ads_ready = ad_accounts_response.ok and "ads_read" in granted and bool(ad_accounts_payload.get("data"))
    return {
        "valid": response.ok and bool(instagram_accounts),
        "instagram_accounts": len(instagram_accounts),
        "ads_ready": ads_ready,
        "ad_accounts": len(ad_accounts_payload.get("data") or []),
        "required_ads_permissions": {
            "ads_read": "ads_read" in granted,
            "ads_management": "ads_management" in granted,
            "business_management": "business_management" in granted,
            "read_insights": "read_insights" in granted,
        },
        "error": "" if response.ok else (payload.get("error") or {}).get("message", "Instagram ENV tokenı doğrulanamadı."),
    }


def _validate_meta_ad_library_token(token):
    response = requests.get(
        f"{settings.FACEBOOK_GRAPH_URL}/ads_archive",
        params={
            "access_token": token,
            "ad_reached_countries": "TR",
            "search_terms": "reklam",
            "fields": "id",
            "limit": 1,
        },
        timeout=30,
    )
    payload = response.json()
    error = payload.get("error") or {}
    return {
        "valid": response.ok and not error,
        "error_code": error.get("code"),
        "error": error.get("message", "") if error else "",
    }


def _record_env_failure(label, message):
    diagnostic_message = str(message or "ENV token kontrolu basarisiz oldu.")[:500]
    full_message = f"{label}: {diagnostic_message}"
    since = timezone.now() - ENV_FAILURE_DEDUPE_WINDOW
    existing = SystemErrorLog.objects.filter(
        severity="critical",
        status__in=("new", "investigating"),
        message=full_message,
        tags__source="platform_token_health",
        tags__token_label=label,
        created_at__gte=since,
    ).order_by("-created_at").first()
    if existing:
        return existing

    return SystemErrorLog.objects.create(
        error_id=f"ENV-{uuid.uuid4().hex[:16].upper()}",
        message=full_message,
        severity="critical",
        status="new",
        file_name="core/services/platform_token_service.py",
        function_name="_notify_admins_for_env_failure",
        tags={
            "source": "platform_token_health",
            "category": "env_token",
            "token_label": label,
        },
        extra_data={"diagnostic_message": diagnostic_message},
    )


def _notify_admins_for_env_failure(label, message):
    try:
        error_log = _record_env_failure(label, message)
        target_link = reverse("admin:core_systemerrorlog_change", args=[error_log.pk])
    except Exception as exc:
        logger.exception("ENV token hata kaydi olusturulamadi: %s", exc)
        target_link = reverse("admin:core_systemerrorlog_changelist")

    admins = get_user_model().objects.filter(is_active=True, is_staff=True)
    for user in admins:
        NotificationHelper.notify(
            user,
            f"Kritik ENV token hatası: {label}",
            message[:300],
            "critical",
            "🚨",
            target_link,
            dedupe_minutes=360,
        )


def check_and_refresh_platform_tokens():
    now = timezone.now()
    results = []
    connections = PlatformConnection.objects.select_related("platform").filter(is_active=True)
    for connection in connections:
        token = connection.access_token or ""
        row = {"connection_id": connection.id, "platform": connection.platform.code}
        try:
            health = _validate_connection(connection)
            expiry = health.get("expires_at") or health.get("data_access_expires_at") or connection.token_expiry
            if expiry:
                connection.token_expiry = expiry
            if not health.get("valid"):
                connection.status = "expired"
                row.update({"valid": False, "status": "expired"})
                _notify_connection_issue(connection, "Token API tarafından reddedildi; yeniden yetkilendirme gerekli.", critical=True)
            elif connection.platform.code == "instagram" and expiry and expiry <= now + REFRESH_WINDOW:
                new_token, expires_in = _refresh_instagram_token(token)
                if new_token:
                    connection.access_token = new_token
                    connection.accounts.update(access_token=new_token)
                if expires_in:
                    connection.token_expiry = now + timedelta(seconds=expires_in)
                connection.status = "active"
                row.update({"valid": True, "status": "refreshed"})
            else:
                connection.status = "active"
                row.update({"valid": True, "status": "active"})
            connection.extra_data = {**(connection.extra_data or {}), "token_health_checked_at": now.isoformat(), "token_health_status": row["status"], "token_health_failure_count": 0}
            connection.save(update_fields=["access_token", "token_expiry", "status", "extra_data", "updated_at"])
        except Exception as exc:
            row.update({"valid": None, "status": "check_failed", "error": _safe_error(exc, token)})
            failure_count = int((connection.extra_data or {}).get("token_health_failure_count") or 0) + 1
            connection.extra_data = {**(connection.extra_data or {}), "token_health_checked_at": now.isoformat(), "token_health_status": "check_failed", "token_health_error": row["error"], "token_health_failure_count": failure_count}
            connection.save(update_fields=["extra_data", "updated_at"])
            if failure_count >= 3:
                _notify_connection_issue(connection, f"Token kontrolü {failure_count} kez üst üste başarısız oldu.")
        results.append(row)
    env_token = getattr(settings, "INSTAGRAM_ACCESS_TOKEN", "") or ""
    env_result = {"configured": bool(env_token), "valid": None}
    if env_token:
        try:
            env_result.update(_validate_env_instagram_token(env_token))
            if not env_result["valid"]:
                _notify_admins_for_env_failure("INSTAGRAM_ACCESS_TOKEN", env_result.get("error") or "Instagram hesabına erişilemiyor.")
            elif not env_result.get("ads_ready"):
                _notify_admins_for_env_failure("INSTAGRAM_ACCESS_TOKEN", "Token geçerli fakat ads_read izni veya erişilebilir reklam hesabı yok.")
        except Exception as exc:
            env_result["error"] = _safe_error(exc, env_token)

    ad_library_token = getattr(settings, "META_AD_LIBRARY_ACCESS_TOKEN", "") or ""
    ad_library_result = {"configured": bool(ad_library_token), "valid": None}
    if ad_library_token:
        try:
            ad_library_result.update(_validate_meta_ad_library_token(ad_library_token))
            if not ad_library_result["valid"]:
                _notify_admins_for_env_failure("META_AD_LIBRARY_ACCESS_TOKEN", ad_library_result.get("error") or "Ad Library erişimi yok.")
        except Exception as exc:
            ad_library_result["error"] = _safe_error(exc, ad_library_token)

    result = {
        "success": True,
        "checked": len(results),
        "active": sum(1 for row in results if row.get("status") in {"active", "refreshed"}),
        "refreshed": sum(1 for row in results if row.get("status") == "refreshed"),
        "expired": sum(1 for row in results if row.get("status") == "expired"),
        "check_failed": sum(1 for row in results if row.get("status") == "check_failed"),
        "env_instagram": env_result,
        "env_meta_ad_library": ad_library_result,
        "results": results,
    }
    cache.set(HEALTH_CACHE_KEY, result, timeout=60 * 60 * 2)
    return result
