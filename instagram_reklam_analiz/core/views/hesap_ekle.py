from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
import requests

from core.models import AnalyticsProperty, Platform, PlatformAccount, PlatformConnection
from core.services.cache_service import CacheService
from core.services.notification_helper import NotificationHelper


PLATFORM_DEFAULTS = {
    "instagram": {"name": "Instagram", "icon": "fab fa-instagram"},
    "facebook": {"name": "Facebook", "icon": "fab fa-facebook"},
    "google_ads": {"name": "Google Ads", "icon": "fab fa-google"},
    "youtube": {"name": "YouTube", "icon": "fab fa-youtube"},
    "tiktok": {"name": "TikTok", "icon": "fab fa-tiktok"},
    "linkedin": {"name": "LinkedIn", "icon": "fab fa-linkedin"},
    "x": {"name": "X", "icon": "fab fa-x-twitter"},
    "google_analytics": {"name": "Google Analytics 4", "icon": "fas fa-chart-pie"},
}


def _graph_get(url, access_token, fields):
    response = requests.get(
        url,
        params={"fields": fields, "access_token": access_token},
        timeout=30,
    )
    data = response.json()
    if not response.ok:
        error = data.get("error") or {}
        raise ValueError(error.get("message") or "Token doğrulanamadı.")
    return data


def _resolve_instagram_accounts(access_token):
    graph_url = getattr(settings, "FACEBOOK_GRAPH_URL", "https://graph.facebook.com/v25.0")
    accounts_data = _graph_get(
        f"{graph_url}/me/accounts",
        access_token,
        "id,name,access_token,instagram_business_account{id,username,media_count}",
    )
    resolved = []
    for page in accounts_data.get("data", []):
        instagram = page.get("instagram_business_account") or {}
        if instagram.get("id") and instagram.get("username"):
            resolved.append({
                "instagram_id": str(instagram["id"]),
                "username": str(instagram["username"]).lstrip("@"),
                "account_type": instagram.get("account_type") or "",
                "media_count": instagram.get("media_count"),
                "page_id": str(page.get("id") or ""),
                "page_name": page.get("name") or "",
                "access_token": page.get("access_token") or access_token,
            })

    if resolved:
        return resolved

    # Instagram Login / Basic Display tokenları için doğrudan hesap doğrulaması.
    instagram = _graph_get(
        "https://graph.instagram.com/me",
        access_token,
        "id,username,account_type,media_count",
    )
    if instagram.get("id") and instagram.get("username"):
        return [{
            "instagram_id": str(instagram["id"]),
            "username": str(instagram["username"]).lstrip("@"),
            "account_type": instagram.get("account_type") or "",
            "media_count": instagram.get("media_count"),
            "page_id": "",
            "page_name": "",
            "access_token": access_token,
        }]
    raise ValueError("Bu tokena bağlı doğrulanabilir bir Instagram hesabı bulunamadı.")


def _save_verified_instagram_accounts(user, platform, access_token, agency_client=None):
    verified_accounts = _resolve_instagram_accounts(access_token)
    from core.services.plan_limits import ensure_platform_account_capacity
    candidates = []
    for verified in verified_accounts:
        candidates.append((platform.code, verified["instagram_id"]))
        if verified.get("page_id"):
            candidates.append(("facebook", verified["page_id"]))
    organization = agency_client.organization if agency_client else None
    ensure_platform_account_capacity(user, candidates, organization=organization)
    saved = []
    for verified in verified_accounts:
        instagram_id = verified["instagram_id"]
        username = verified["username"]
        # Page token organik uç noktalarda çalışsa da reklam hesaplarını listeleyemez.
        # Kullanıcının verdiği ana OAuth tokenı ads_read/ads_management ve organik
        # işlemlerin ikisini birlikte taşıdığı için kalıcı bağlantıda onu koru.
        verified_token = access_token
        account = (
            PlatformAccount.objects.filter(user=user, platform=platform)
            .filter(
                Q(account_id=instagram_id)
                | Q(extra_data__instagram_business_account_id=instagram_id)
            )
            .select_related("connection")
            .first()
        )
        created = account is None
        if created:
            account = PlatformAccount(user=user, platform=platform, account_id=instagram_id)

        connection = account.connection if account.connection_id else PlatformConnection(
            user=user,
            platform=platform,
        )
        connection.name = f"Instagram @{username}"
        connection.access_token = verified_token
        connection.status = "active"
        connection.is_active = True
        connection.last_sync = timezone.now()
        connection.extra_data = {
            **(connection.extra_data or {}),
            "source": "instagram_token_verification",
            "verified_at": timezone.now().isoformat(),
            "instagram_business_account_id": instagram_id,
            "instagram_username": username,
            "facebook_page_id": verified["page_id"],
            "facebook_page_name": verified["page_name"],
        }
        connection.save()

        account.account_name = f"@{username}"
        account.agency_client = agency_client
        account.access_token = verified_token
        account.connection = connection
        account.is_active = True
        account.last_sync = timezone.now()
        account.extra_data = {
            **(account.extra_data or {}),
            "instagram_business_account_id": instagram_id,
            "instagram_username": username,
            "instagram_account_type": verified["account_type"],
            "instagram_media_count": verified["media_count"],
            "facebook_page_id": verified["page_id"],
            "facebook_page_name": verified["page_name"],
            "verified_at": timezone.now().isoformat(),
        }
        account.save()
        if verified.get("page_id"):
            facebook_platform, _ = Platform.objects.get_or_create(
                code="facebook", defaults={"name": "Facebook", "is_active": True}
            )
            facebook_connection = PlatformConnection.objects.filter(
                user=user,
                platform=facebook_platform,
                extra_data__facebook_page_id=verified["page_id"],
            ).first() or PlatformConnection(user=user, platform=facebook_platform)
            facebook_connection.name = f"Facebook {verified['page_name'] or username}"
            facebook_connection.access_token = verified["access_token"]
            facebook_connection.status = "active"
            facebook_connection.is_active = True
            facebook_connection.extra_data = {
                **(facebook_connection.extra_data or {}),
                "source": "instagram_page_discovery",
                "facebook_page_id": verified["page_id"],
                "instagram_business_account_id": instagram_id,
            }
            facebook_connection.save()
            facebook_account, _ = PlatformAccount.objects.update_or_create(
                user=user,
                platform=facebook_platform,
                account_id=verified["page_id"],
                defaults={
                    "agency_client": agency_client,
                    "connection": facebook_connection,
                    "account_name": verified["page_name"] or f"Facebook @{username}",
                    "access_token": verified["access_token"],
                    "is_active": True,
                    "extra_data": {
                        "source": "instagram_page_discovery",
                        "facebook_page_id": verified["page_id"],
                        "instagram_business_account_id": instagram_id,
                    },
                },
            )
        saved.append((account, created))
    return saved


def _bearer_get(url, access_token, params=None):
    response = requests.get(url, params=params or {}, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    data = response.json()
    if not response.ok:
        error = data.get("error") or data.get("errors") or data.get("message") or {}
        if isinstance(error, dict):
            error = error.get("message") or error.get("description") or str(error)
        raise ValueError(str(error) or "Kimlik bilgisi doğrulanamadı.")
    return data


def _resolve_token_platform_accounts(platform_code, access_token):
    if platform_code == "facebook":
        graph_url = getattr(settings, "FACEBOOK_GRAPH_URL", "https://graph.facebook.com/v25.0")
        data = _graph_get(f"{graph_url}/me/adaccounts", access_token, "id,name,account_status,currency,timezone_name")
        return [{"id": str(r["id"]), "name": r.get("name") or str(r["id"]), "extra_data": r} for r in data.get("data", []) if r.get("id")]
    if platform_code == "youtube":
        data = _bearer_get("https://www.googleapis.com/youtube/v3/channels", access_token, {"part": "snippet,statistics", "mine": "true"})
        return [{"id": str(r["id"]), "name": (r.get("snippet") or {}).get("title") or str(r["id"]), "extra_data": r} for r in data.get("items", []) if r.get("id")]
    if platform_code == "tiktok":
        data = _bearer_get("https://open.tiktokapis.com/v2/user/info/", access_token, {"fields": "open_id,union_id,display_name,username,avatar_url"})
        row = (data.get("data") or {}).get("user") or {}; account_id = row.get("open_id") or row.get("union_id"); username = row.get("username") or row.get("display_name")
        return [{"id": str(account_id), "name": f"@{str(username).lstrip('@')}", "extra_data": row}] if account_id and username else []
    if platform_code == "linkedin":
        row = _bearer_get("https://api.linkedin.com/v2/userinfo", access_token); account_id = row.get("sub"); name = row.get("name") or row.get("preferred_username") or row.get("email")
        return [{"id": str(account_id), "name": str(name), "extra_data": row}] if account_id and name else []
    if platform_code == "x":
        data = _bearer_get("https://api.x.com/2/users/me", access_token, {"user.fields": "id,name,username,profile_image_url"}); row = data.get("data") or {}
        return [{"id": str(row["id"]), "name": f"@{str(row['username']).lstrip('@')}", "extra_data": row}] if row.get("id") and row.get("username") else []
    raise ValueError("Bu platform token ile otomatik doğrulamayı desteklemiyor.")


def _save_verified_token_accounts(user, platform, access_token, agency_client=None):
    verified_accounts = _resolve_token_platform_accounts(platform.code, access_token)
    if not verified_accounts:
        raise ValueError("Bu kimlik bilgisine bağlı erişilebilir hesap bulunamadı.")
    from core.services.plan_limits import ensure_platform_account_capacity
    organization = agency_client.organization if agency_client else None
    ensure_platform_account_capacity(
        user,
        [(platform.code, verified["id"]) for verified in verified_accounts],
        organization=organization,
    )
    saved = []
    for verified in verified_accounts:
        account, created = PlatformAccount.objects.get_or_create(user=user, platform=platform, account_id=verified["id"], defaults={"account_name": verified["name"], "access_token": access_token, "agency_client": agency_client})
        connection = account.connection if account.connection_id else PlatformConnection(user=user, platform=platform)
        connection.name = f"{platform.name} {verified['name']}"; connection.access_token = access_token; connection.status = "active"; connection.is_active = True; connection.last_sync = timezone.now()
        connection.extra_data = {**(connection.extra_data or {}), "source": "token_verification", "verified_at": timezone.now().isoformat()}; connection.save()
        account.account_name = verified["name"]; account.access_token = access_token; account.connection = connection; account.agency_client = agency_client; account.is_active = True; account.last_sync = timezone.now()
        account.extra_data = {**(account.extra_data or {}), **verified["extra_data"], "verified_at": timezone.now().isoformat()}; account.save(); saved.append((account, created))
    CacheService.bump_version("ads_panel_accounts", user.id)
    return saved


@login_required
def hesap_ekle_view(request):
    from core.services.agency_scope import get_agency_scope
    agency_scope = get_agency_scope(request)
    if agency_scope.is_agency:
        messages.warning(request, "Ajans hesapları bu ekrandan bağlanamaz. Önce ajans müşterisini seçip müşteri detayındaki Hesap Bağla alanını kullanın.")
        return redirect("agency_dashboard_org", organization_id=agency_scope.organization_ids[0])
    if request.method == "POST":
        platform_code = request.POST.get("platform")
        account_name = request.POST.get("account_name", "").strip()
        account_id = request.POST.get("account_id", "").strip()
        access_token = request.POST.get("access_token", "").strip()

        defaults = PLATFORM_DEFAULTS.get(platform_code)
        if not defaults:
            messages.error(request, f"{platform_code} platformu desteklenmiyor.")
            return redirect("hesap_ekle")

        platform, _ = Platform.objects.get_or_create(
            code=platform_code,
            defaults={**defaults, "is_active": True},
        )

        if platform_code == "instagram":
            if not access_token:
                messages.error(request, "Instagram access tokenı zorunludur.")
                return redirect("hesap_ekle")
            try:
                saved_accounts = _save_verified_instagram_accounts(
                    request.user, platform, access_token
                )
            except (requests.RequestException, ValueError) as exc:
                messages.error(request, f"Instagram hesabı doğrulanamadı: {exc}")
                return redirect("hesap_ekle")

            for account, created in saved_accounts:
                NotificationHelper.platform_account_connected(
                    user=request.user, account=account, created=created
                )
            usernames = ", ".join(account.account_name for account, _ in saved_accounts)
            messages.success(request, f"Instagram hesabı doğrulandı ve bağlandı: {usernames}")
            return redirect("hesap_ekle")

        if platform_code in {"facebook", "youtube", "tiktok", "linkedin", "x"}:
            if not access_token:
                messages.error(request, f"{platform.name} access tokenı zorunludur.")
                return redirect("hesap_ekle")
            try:
                saved_accounts = _save_verified_token_accounts(request.user, platform, access_token)
            except (requests.RequestException, ValueError) as exc:
                messages.error(request, f"{platform.name} hesabı doğrulanamadı: {exc}")
                return redirect("hesap_ekle")
            for account, created in saved_accounts:
                NotificationHelper.platform_account_connected(user=request.user, account=account, created=created)
            names = ", ".join(account.account_name for account, _ in saved_accounts)
            messages.success(request, f"{platform.name} hesabı doğrulandı ve bağlandı: {names}")
            return redirect("hesap_ekle")

        account_id = account_id or account_name
        from core.services.plan_limits import ensure_platform_account_capacity
        ensure_platform_account_capacity(request.user, [(platform.code, account_id)])
        account, created = PlatformAccount.objects.get_or_create(
            user=request.user,
            platform=platform,
            account_id=account_id,
            defaults={
                "account_name": account_name,
                "access_token": access_token,
                "is_active": True,
            },
        )

        if not created:
            account.account_name = account_name
            account.access_token = access_token
            account.is_active = True
            account.save(update_fields=["account_name", "access_token", "is_active", "updated_at"])

        if platform_code == "google_analytics":
            AnalyticsProperty.objects.update_or_create(
                user=request.user,
                platform_account=account,
                property_id=account_id,
                defaults={
                    "property_name": account_name or f"GA4 Property {account_id}",
                    "property_type": "GA4",
                    "raw_data": {
                        "source": "manual_connection",
                        "account_id": account_id,
                        "account_name": account_name,
                    },
                    "is_active": True,
                },
            )

        NotificationHelper.platform_account_connected(
            user=request.user,
            account=account,
            created=created,
        )

        status = "eklendi" if created else "guncellendi"
        messages.success(request, f"{platform.name} hesabi {status}.")
        return redirect("hesap_ekle")

    platform_accounts = (
        PlatformAccount.objects
        .filter(user=request.user)
        .select_related("platform", "agency_client")
        .order_by("platform__name", "account_name", "account_id")
    )
    return render(request, "hesap_ekle.html", {"platform_accounts": platform_accounts})


@login_required
def hesap_sil(request, account_id):
    account = get_object_or_404(PlatformAccount, id=account_id, user=request.user)
    account_label = str(account)

    NotificationHelper.notify(
        user=request.user,
        title="Platform hesabi silindi",
        message=f"{account_label} hesabi sistemden kaldirildi.",
        level="warning",
        icon="trash",
        link="/hesap-ekle/",
        dedupe_minutes=1,
    )

    account.delete()
    messages.success(request, "Hesap basariyla silindi.")
    return redirect("hesap_ekle")
