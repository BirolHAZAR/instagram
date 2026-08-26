from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import InstagramAccount, PlatformAccount, Ad, AdMetricHistory
from core.tasks.v2_platform_sync import sync_v2_platform_account_ads
from core.services.sync_policy import is_sync_due, manual_sync_allowed, policy_for_user

@login_required
def instagram_dashboard(request):
    accounts = InstagramAccount.objects.filter(user=request.user)
    platform_accounts = PlatformAccount.objects.filter(user=request.user, platform__code="instagram")
    return render(request, "instagram/dashboard.html", {"accounts": accounts, "platform_accounts": platform_accounts, "v2_only": True})


@login_required
def add_instagram_account(request):
    if request.method == "POST":
        username = request.POST.get("username") or request.POST.get("account_name") or "instagram"
        account, _ = InstagramAccount.objects.get_or_create(user=request.user, username=username, defaults={"is_active": True})
        messages.success(request, "Instagram hesabı kaydedildi.")
        return redirect("instagram_dashboard")
    return render(request, "instagram/add_account.html", {"v2_only": True})


@login_required
def instagram_account_detail(request, account_id):
    account = get_object_or_404(InstagramAccount, id=account_id, user=request.user)
    return render(request, "instagram/account_detail.html", {"account": account, "v2_only": True})


@login_required
def sync_instagram_data(request, account_id):
    account = get_object_or_404(InstagramAccount, id=account_id, user=request.user)
    account.last_sync = timezone.now() if hasattr(account, "last_sync") else getattr(account, "last_sync", None)
    try:
        account.save()
    except Exception:
        pass
    return JsonResponse({"success": True, "message": "Instagram organik sync V2 modda işaretlendi."})


@login_required
def delete_instagram_account(request, account_id):
    InstagramAccount.objects.filter(id=account_id, user=request.user).update(is_active=False)
    return redirect("instagram_dashboard")


@login_required
def fetch_instagram_ads(request, account_id):
    platform_account = PlatformAccount.objects.filter(id=account_id, user=request.user, platform__code="instagram").first()
    if not manual_sync_allowed(request.user, "ad"):
        return JsonResponse({"success": False, "message": "Paketiniz manuel reklam yenilemeye izin vermiyor."}, status=403)
    if not platform_account:
        return JsonResponse({"success": False, "message": "V2 PlatformAccount bulunamadı."}, status=404)
    if not is_sync_due(request.user, platform_account.last_sync, kind="ad"):
        policy = policy_for_user(request.user)
        return JsonResponse({
            "success": False,
            "message": f"Paketinizde veri güncelleme aralığı {policy.ad_interval_minutes} dakikadır. Mevcut güncel veri gösteriliyor.",
        }, status=429)
    task = sync_v2_platform_account_ads.delay(platform_account.id)
    return JsonResponse({"success": True, "task_id": task.id, "message": "V2 reklam senkronizasyonu başlatıldı."})


@login_required
def get_instagram_stats(request, account_id):
    platform_account = PlatformAccount.objects.filter(id=account_id, user=request.user).first()
    qs = AdMetricHistory.objects.filter(ad__user=request.user, ad__platform_account=platform_account, ad__source_type="OWN")
    return JsonResponse({"success": True, "ads_count": Ad.objects.filter(user=request.user, platform_account=platform_account, source_type="OWN").count(), "metrics_count": qs.count()})


@login_required
def instagram_reklam_raporu(request):
    ads = (
        Ad.objects.filter(
            user=request.user,
            source_type="OWN",
            platform_account__platform__code="instagram",
        )
        .select_related("platform_account", "campaign", "ad_group", "creative")
        .prefetch_related("metric_history")
        .order_by("-updated_at", "-created_at")
    )
    metrics = AdMetricHistory.objects.filter(ad__in=ads)
    summary = metrics.aggregate(
        impressions=Sum("impressions"),
        clicks=Sum("clicks"),
        spend=Sum("spend"),
        conversions=Sum("conversions"),
        ctr=Avg("ctr"),
        cpc=Avg("cpc"),
        roas=Avg("roas"),
        engagement_rate=Avg("engagement_rate"),
    )

    return render(
        request,
        "instagram/ad_report.html",
        {
            "ads": ads,
            "summary": summary,
            "v2_only": True,
        },
    )
