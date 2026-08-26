# core/views/platform_connect.py
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.db import IntegrityError
from django.views.decorators.http import require_POST
import requests

from core.models import PlatformAccount, Platform
from core.services.notification_helper import NotificationHelper


# ==================== FACEBOOK OAUTH ====================
@login_required
def facebook_login(request):
    redirect_uri = settings.FACEBOOK_REDIRECT_URI
    params = {
        'client_id': settings.FACEBOOK_APP_ID,
        'redirect_uri': redirect_uri,
        'scope': 'ads_management,ads_read,business_management',
        'response_type': 'code',
        'state': str(request.user.id),
    }
    url = 'https://www.facebook.com/v25.0/dialog/oauth?' + '&'.join(f'{k}={v}' for k, v in params.items())
    return redirect(url)


@login_required
def facebook_callback(request):
    code = request.GET.get('code')
    if not code:
        messages.error(request, 'Facebook bağlantısı tamamlanamadı. Yetkilendirme kodu alınamadı.')
        return redirect('dashboard')

    token_url = 'https://graph.facebook.com/v25.0/oauth/access_token'
    params = {
        'client_id': settings.FACEBOOK_APP_ID,
        'client_secret': settings.FACEBOOK_APP_SECRET,
        'redirect_uri': settings.FACEBOOK_REDIRECT_URI,
        'code': code,
    }

    try:
        resp = requests.get(token_url, params=params, timeout=20)
        data = resp.json()
        access_token = data.get('access_token')

        if not access_token:
            messages.error(request, 'Facebook access token alınamadı.')
            return redirect('hesap_ekle')

        me_url = 'https://graph.facebook.com/me'
        me_resp = requests.get(
            me_url,
            params={'access_token': access_token, 'fields': 'id,name'},
            timeout=20,
        )
        me_data = me_resp.json()
        account_id = me_data.get('id')
        account_name = me_data.get('name') or 'Facebook Hesabı'

        if not account_id:
            messages.error(request, 'Facebook hesap bilgileri alınamadı.')
            return redirect('hesap_ekle')

        platform, _ = Platform.objects.get_or_create(
            code='facebook',
            defaults={'name': 'Facebook', 'is_active': True}
        )

        from core.services.plan_limits import ensure_platform_account_capacity
        ensure_platform_account_capacity(request.user, [(platform.code, account_id)])

        account, created = PlatformAccount.objects.update_or_create(
            user=request.user,
            platform=platform,
            account_id=account_id,
            defaults={
                'account_name': account_name,
                'access_token': access_token,
                'is_active': True,
            }
        )

        NotificationHelper.platform_account_connected(
            user=request.user,
            account=account,
            created=created,
        )

        try:
            from core.tasks import sync_facebook_ads
            sync_facebook_ads.delay(account_id)
        except Exception:
            # Senkronizasyon task'ı hata verse bile hesap bağlantısı ve bildirimi bozulmasın.
            pass

        messages.success(request, f'Facebook hesabı {"bağlandı" if created else "güncellendi"}: {account_name}')
        return redirect('hesap_ekle')

    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('hesap_ekle')
    except Exception as exc:
        NotificationHelper.notify(
            user=request.user,
            title='Facebook bağlantı hatası',
            message=f'Facebook hesabı bağlanırken hata oluştu: {str(exc)[:140]}',
            level='warning',
            icon='⚠️',
            link='/hesap-ekle/',
            dedupe_minutes=5,
        )
        messages.error(request, 'Facebook bağlantısı sırasında hata oluştu.')
        return redirect('hesap_ekle')

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.models import Platform, PlatformAccount, PlatformConnection


@login_required
def platform_connections(request):
    user = request.user

    platforms = Platform.objects.filter(is_active=True).order_by("name")
    platform_data = []
    total_account_count = 0
    total_active_account_count = 0
    total_connection_count = 0
    total_active_connection_count = 0

    for platform in platforms:
        connections = list(
            PlatformConnection.objects
            .filter(user=user, platform=platform)
            .prefetch_related("accounts")
            .order_by("-created_at")
        )

        accounts = list(
            PlatformAccount.objects
            .filter(user=user, platform=platform)
            .select_related("connection")
            .order_by("account_name", "account_id")
        )

        account_count = len(accounts)
        active_account_count = sum(1 for account in accounts if account.is_active)
        connection_count = len(connections)
        active_connection_count = sum(
            1 for connection in connections
            if connection.status == "active" and connection.is_active and connection.access_token
        )
        standalone_token_count = sum(
            1 for account in accounts
            if not account.connection_id and account.is_active and account.access_token
        )
        active_token_count = active_connection_count + standalone_token_count

        total_account_count += account_count
        total_active_account_count += active_account_count
        total_connection_count += connection_count
        total_active_connection_count += active_token_count

        platform_data.append({
            "platform": platform,
            "connections": connections,
            "accounts": accounts,
            "account_count": account_count,
            "active_account_count": active_account_count,
            "connection_count": connection_count,
            "active_connection_count": active_connection_count,
            "active_token_count": active_token_count,
        })
    return render(request, "platforms/platform_connections.html", {
        "platform_data": platform_data,
        "total_account_count": total_account_count,
        "total_active_account_count": total_active_account_count,
        "total_connection_count": total_connection_count,
        "total_active_connection_count": total_active_connection_count,
    })


@login_required
@require_POST
def platform_account_update(request, account_id):
    account = get_object_or_404(
        PlatformAccount.objects.select_related("platform"),
        id=account_id,
        user=request.user,
    )
    account_name = request.POST.get("account_name", "").strip()
    external_account_id = request.POST.get("account_id", "").strip()
    connection_id = request.POST.get("connection", "").strip()

    if not external_account_id:
        messages.error(request, "Platform ID boş bırakılamaz.")
        return redirect("platform_connections")

    connection = None
    if connection_id:
        connection = get_object_or_404(
            PlatformConnection,
            id=connection_id,
            user=request.user,
            platform=account.platform,
        )

    account.account_name = account_name
    account.account_id = external_account_id
    account.connection = connection
    account.is_active = request.POST.get("is_active") == "on"
    try:
        account.save(update_fields=[
            "account_name", "account_id", "connection", "is_active", "updated_at"
        ])
    except IntegrityError:
        messages.error(request, "Bu Platform ID aynı platformda zaten kayıtlı.")
    else:
        messages.success(request, f"{account.account_name or account.account_id} hesabı güncellendi.")
    return redirect("platform_connections")


@login_required
@require_POST
def platform_account_delete(request, account_id):
    account = get_object_or_404(PlatformAccount, id=account_id, user=request.user)
    account_label = account.account_name or account.account_id
    account.delete()
    messages.success(request, f"{account_label} hesabı silindi.")
    return redirect("platform_connections")
