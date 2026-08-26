from __future__ import annotations

import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.models import OrganizationMember, PlatformAccount, PlatformConnection, SocialPost, SocialPostMetricHistory
from core.services.cache_service import CacheService
from core.services.agency_scope import get_agency_scope, platform_accounts_for_request
from core.services.organic_content_service import (
    decorate_posts,
    sync_instagram_organic_content,
)
from core.services.organic_publish import publish_post
from core.services.sync_policy import is_sync_due, manual_sync_allowed, policy_for_user
from core.services.organic_platforms import ORGANIC_PUBLISH_PLATFORM_CODES, organic_publish_platform_rows
from core.utils.translations import TRANSLATIONS, get_user_language


SUPPORTED_ORGANIC_PLATFORM_CODES = ORGANIC_PUBLISH_PLATFORM_CODES


def _request_labels(request):
    language = request.session.get("preferred_language") or get_user_language(request.user)
    return TRANSLATIONS.get(language, TRANSLATIONS["tr"])


def _localized_supported_platforms(labels):
    platforms = []
    for platform in organic_publish_platform_rows():
        row = {**platform, "key": platform["code"]}
        enabled = platform["live_enabled"]
        row["status_key"] = "ready" if enabled else "planned"
        row["status"] = (
            "Canlı yayın aktif"
            if enabled
            else "Canlı yayın ayarı kapalı"
        )
        platforms.append(row)
    return platforms


def _user_connections(user):
    return (
        PlatformConnection.objects.select_related("platform")
        .filter(user=user, is_active=True, platform__code__in=SUPPORTED_ORGANIC_PLATFORM_CODES)
        .order_by("platform__name", "name")
    )


def _accessible_organization_ids(user):
    member_org_ids = OrganizationMember.objects.filter(
        user=user,
        is_active=True,
        organization__is_active=True,
    ).values_list("organization_id", flat=True)
    owned_org_ids = user.owned_organizations.filter(is_active=True).values_list("id", flat=True)
    return list(set(member_org_ids) | set(owned_org_ids))


def _accessible_platform_accounts(user):
    org_ids = _accessible_organization_ids(user)
    filters = Q(user=user)
    if org_ids:
        filters |= Q(agency_client__organization_id__in=org_ids)
    return (
        PlatformAccount.objects.select_related(
            "platform",
            "connection",
            "connection__platform",
            "agency_client",
            "agency_client__organization",
        )
        .filter(filters, is_active=True)
        .filter(platform__code__in=SUPPORTED_ORGANIC_PLATFORM_CODES)
        .distinct()
        .order_by("agency_client__name", "platform__name", "account_name", "account_id")
    )


def _scoped_platform_accounts(request):
    return (
        platform_accounts_for_request(request, active_only=True)
        .select_related(
            "platform", "connection", "connection__platform",
            "agency_client", "agency_client__organization",
        )
        .filter(platform__code__in=SUPPORTED_ORGANIC_PLATFORM_CODES)
        .distinct()
        .order_by("agency_client__name", "platform__name", "account_name", "account_id")
    )


@login_required
def organic_content_center(request):
    labels = _request_labels(request)
    agency_scope = get_agency_scope(request)
    today = timezone.localdate()
    selected_period = request.GET.get("period", "weekly").strip() or "weekly"
    end_date = today
    if selected_period == "daily":
        start_date = today
    elif selected_period == "monthly":
        start_date = today - timedelta(days=29)
    elif selected_period == "quarterly":
        start_date = today - timedelta(days=89)
    elif selected_period == "custom":
        start_date = parse_date(request.GET.get("start_date", "")) or (today - timedelta(days=6))
        end_date = parse_date(request.GET.get("end_date", "")) or today
        if start_date > end_date:
            start_date, end_date = end_date, start_date
    else:
        selected_period = "weekly"
        start_date = today - timedelta(days=6)
    selected_platform = request.GET.get("platform", "").strip()
    selected_type = request.GET.get("type", "").strip()
    version = CacheService.get_version("organic_content", request.user.id)
    cache_parts = ("user", request.user.id, "scope", agency_scope.cache_key, "source", "platform-sync-v1", "period", selected_period, "start", start_date.isoformat(), "end", end_date.isoformat(), "platform", selected_platform or "all", "type", selected_type or "all")
    cached = CacheService.get("organic_content", *cache_parts, version=version)
    if cached is not None:
        cached = dict(cached)
        cached["agency_scope"] = agency_scope
        return render(request, "social_content/organic_content_center.html", cached)
    accounts = _scoped_platform_accounts(request)
    account_ids = list(accounts.values_list("id", flat=True))

    posts = (
        SocialPost.objects.select_related(
            "platform_connection",
            "platform_connection__platform",
            "platform_account",
            "platform_account__platform",
            "platform_account__agency_client",
            "platform_account__agency_client__organization",
        )
        .filter(
            Q(platform_account_id__in=account_ids)
            if agency_scope.selected_client
            else (Q(user=request.user) | Q(platform_account_id__in=account_ids))
        )
        .filter(
            Q(platform_account__platform__code__in=SUPPORTED_ORGANIC_PLATFORM_CODES)
            | Q(platform_connection__platform__code__in=SUPPORTED_ORGANIC_PLATFORM_CODES)
        )
        .filter(raw_data__source="instagram_media_sync")
        .distinct()
        .order_by("-posted_at", "-created_at")
    )

    if selected_platform:
        posts = posts.filter(platform_connection__platform__name__icontains=selected_platform)
    if selected_type:
        posts = posts.filter(post_type=selected_type)

    post_ids = list(posts.values_list("id", flat=True)[:500])
    metrics = SocialPostMetricHistory.objects.filter(
        social_post_id__in=post_ids, date__gte=start_date, date__lte=end_date
    )
    totals = metrics.aggregate(
        impressions=Sum("impressions"), reach=Sum("reach"), engagement=Sum("engagement"),
        likes=Sum("likes"), comments=Sum("comments"), shares=Sum("shares"), saves=Sum("saves"),
        video_views=Sum("video_views"), profile_visits=Sum("profile_visits"), website_clicks=Sum("website_clicks"), latest_date=Max("date")
    )

    post_type_breakdown = posts.values("post_type").annotate(total=Count("id")).order_by("-total")[:6]
    posts_list = decorate_posts(list(posts[:30]), labels=labels)
    visible_post_ids = [post.id for post in posts_list]
    per_post_metrics = {
        row["social_post_id"]: row
        for row in SocialPostMetricHistory.objects.filter(
            social_post_id__in=visible_post_ids, date__gte=start_date, date__lte=end_date
        ).values("social_post_id").annotate(
            impressions=Sum("impressions"), reach=Sum("reach"),
            engagement=Sum("engagement"), likes=Sum("likes"),
            comments=Sum("comments"), shares=Sum("shares"), saves=Sum("saves"),
            video_views=Sum("video_views"), profile_visits=Sum("profile_visits"),
            website_clicks=Sum("website_clicks"), latest_date=Max("date"),
        )
    }
    metric_defaults = {
        "impressions": 0, "reach": 0, "engagement": 0, "likes": 0,
        "comments": 0, "shares": 0, "saves": 0, "video_views": 0,
        "profile_visits": 0, "website_clicks": 0, "latest_date": None,
    }
    for post in posts_list:
        post.organic_metrics = {**metric_defaults, **per_post_metrics.get(post.id, {})}
    total_posts = posts.count()
    active_posts = posts.filter(is_active=True).count()
    published_posts = posts.filter(posted_at__isnull=False).count()
    draft_posts = total_posts - published_posts
    avg_engagement_rate = round(((totals.get("engagement") or 0) / (totals.get("impressions") or 1)) * 100, 2)

    context = {
        "posts": posts_list,
        "agency_scope": agency_scope,
        "connections": _user_connections(request.user),
        "accounts": accounts,
        "supported_platforms": _localized_supported_platforms(labels),
        "selected_platform": selected_platform,
        "selected_type": selected_type,
        "selected_period": selected_period,
        "start_date": start_date,
        "end_date": end_date,
        "post_type_choices": SocialPost.POST_TYPE_CHOICES,
        "post_type_breakdown": post_type_breakdown,
        "stats": {
            "total_posts": total_posts,
            "active_posts": active_posts,
            "draft_posts": draft_posts,
            "published_posts": published_posts,
            "impressions": totals.get("impressions") or 0,
            "reach": totals.get("reach") or 0,
            "engagement": totals.get("engagement") or 0,
            "likes": totals.get("likes") or 0,
            "comments": totals.get("comments") or 0,
            "shares": totals.get("shares") or 0,
            "saves": totals.get("saves") or 0,
            "video_views": totals.get("video_views") or 0,
            "latest_date": totals.get("latest_date"),
            "avg_engagement_rate": avg_engagement_rate,
            "profile_visits": totals.get("profile_visits") or 0,
            "website_clicks": totals.get("website_clicks") or 0,
        },
    }
    CacheService.set("organic_content", *cache_parts, value=context, timeout=120, version=version)
    return render(request, "social_content/organic_content_center.html", context)


@login_required
@require_POST
def organic_content_refresh(request):
    if request.user.username == "demo":
        from core.services.demo_metrics import _refresh_demo_organic_metrics

        metric_count = _refresh_demo_organic_metrics(request.user, timezone.localdate())
        CacheService.bump_version("reports_center", request.user.id)
        CacheService.bump_version("organic_content", request.user.id)
        return JsonResponse({
            "success": True,
            "message": "Demo organik içerik verileri güncellendi.",
            "accounts": 0,
            "created": 0,
            "updated": metric_count,
            "metrics": metric_count,
        })

    if not manual_sync_allowed(request.user, "organic"):
        return JsonResponse({"success": False, "message": "Paketiniz manuel post yenilemeye izin vermiyor."}, status=403)
    accounts = list(_scoped_platform_accounts(request))
    results = []
    for account in accounts:
        if getattr(account.platform, "code", "") != "instagram":
            continue
        extra_data = account.extra_data or {}
        if extra_data.get("demo") or str(account.account_id).startswith("demo-"):
            continue
        result = sync_instagram_organic_content(account)
        results.append({"account_id": account.id, "account": account.account_name or account.account_id, **result})

    CacheService.bump_version("reports_center", request.user.id)
    CacheService.bump_version("organic_content", request.user.id)
    successful = [row for row in results if row.get("success")]
    if successful:
        return JsonResponse({
            "success": True,
            "message": "Organik içerik verileri güncellendi.",
            "accounts": len(successful),
            "created": sum(row.get("created", 0) for row in successful),
            "updated": sum(row.get("updated", 0) for row in successful),
            "metrics": sum(row.get("metrics", 0) for row in successful),
        })
    error = next((row.get("error") for row in results if row.get("error")), "Senkronize edilecek gerçek Instagram hesabı bulunamadı.")
    return JsonResponse({"success": False, "message": error}, status=400)


@login_required
@require_POST
def organic_content_delete(request, post_id):
    agency_scope = get_agency_scope(request)
    account_ids = list(_scoped_platform_accounts(request).values_list("id", flat=True))
    access_filter = (
        Q(platform_account_id__in=account_ids)
        if agency_scope.selected_client
        else (Q(user=request.user) | Q(platform_account_id__in=account_ids))
    )
    post = get_object_or_404(
        SocialPost.objects.filter(access_filter),
        id=post_id,
        raw_data__source="instagram_media_sync",
    )
    post.delete()
    CacheService.bump_version("organic_content", request.user.id)
    CacheService.bump_version("reports_center", request.user.id)
    messages.success(
        request,
        "İçerik yerel merkezden silindi. Instagram'daki gerçek gönderiye dokunulmadı.",
    )
    return redirect("organic_content_center")


@login_required
def organic_content_composer(request):
    labels = _request_labels(request)
    messages.info(request, labels.get("composer_moved_message"))
    return redirect("creative_studio")

    connections = _user_connections(request.user)
    accounts = _accessible_platform_accounts(request.user)

    if request.method == "POST":
        caption = request.POST.get("caption", "").strip()
        post_type = request.POST.get("post_type", "IMAGE").strip() or "IMAGE"
        image_url = request.POST.get("image_url", "").strip()
        video_url = request.POST.get("video_url", "").strip()
        permalink = request.POST.get("permalink", "").strip()
        connection_id = request.POST.get("platform_connection")
        account_id = request.POST.get("platform_account")
        scheduled_at = request.POST.get("scheduled_at", "").strip()

        if not caption and not image_url and not video_url:
            messages.error(request, "İçerik kaydı için en az açıklama, görsel URL veya video URL girmelisin.")
            return redirect("organic_content_composer")

        connection = None
        account = None
        if account_id:
            account = accounts.filter(id=account_id).first()
            if account:
                connection = account.connection
        if connection_id:
            connection = connection or connections.filter(id=connection_id).first()

        raw_data = {"status": "draft", "source": "organic_composer"}
        if scheduled_at:
            raw_data["scheduled_at"] = scheduled_at
            raw_data["status"] = "scheduled"

        SocialPost.objects.create(
            user=request.user,
            platform_connection=connection,
            platform_account=account or (connection.accounts.first() if connection else None),
            platform_post_id=f"draft-{uuid.uuid4().hex[:16]}",
            post_type=post_type if post_type in dict(SocialPost.POST_TYPE_CHOICES) else "UNKNOWN",
            caption=caption,
            permalink=permalink or None,
            image_url=image_url or None,
            video_url=video_url or None,
            thumbnail_url=image_url or None,
            posted_at=None,
            raw_data=raw_data,
            is_active=True,
        )
        messages.success(request, "Organik içerik taslağı oluşturuldu. Yayınlama entegrasyonu platform izinlerine göre sonraki adımda bağlanacak.")
        CacheService.bump_version("reports_center", request.user.id)
        return redirect("organic_content_center")

    return render(request, "social_content/organic_content_composer.html", {
        "connections": connections,
        "accounts": accounts,
        "post_type_choices": SocialPost.POST_TYPE_CHOICES,
        "supported_platforms": _localized_supported_platforms(labels),
    })


@login_required
def organic_connections(request):
    labels = _request_labels(request)
    agency_scope = get_agency_scope(request)
    accounts = _scoped_platform_accounts(request)
    account_ids = list(accounts.values_list("id", flat=True))
    connection_ids = list(accounts.exclude(connection_id=None).values_list("connection_id", flat=True))
    connections = (
        PlatformConnection.objects.select_related("platform")
        .filter(id__in=connection_ids)
        .filter(is_active=True, platform__code__in=SUPPORTED_ORGANIC_PLATFORM_CODES)
        .distinct()
        .order_by("platform__name", "name")
    )
    organic_post_counts = (
        SocialPost.objects.filter(
            platform_account_id__in=account_ids,
            raw_data__source="instagram_media_sync",
        )
        .values("platform_account_id")
        .annotate(total=Count("id"), latest=Max("posted_at"))
    )
    post_count_map = {row["platform_account_id"]: row for row in organic_post_counts}
    for account in accounts:
        account.organic_post_total = post_count_map.get(account.id, {}).get("total", 0)
        account.organic_latest_post_at = post_count_map.get(account.id, {}).get("latest")

    return render(request, "social_content/organic_connections.html", {
        "connections": connections,
        "accounts": accounts,
        "agency_scope": agency_scope,
        "supported_platforms": _localized_supported_platforms(labels),
    })


@login_required
@require_POST
def organic_content_sync_account(request, account_id):
    account = get_object_or_404(_scoped_platform_accounts(request), id=account_id)
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if not manual_sync_allowed(request.user, "organic"):
        message = "Paketiniz manuel post yenilemeye izin vermiyor."
        if wants_json:
            return JsonResponse({"success": False, "message": message}, status=403)
        messages.error(request, message)
        return redirect("organic_connections")
    result = sync_instagram_organic_content(account)
    CacheService.bump_version("reports_center", request.user.id)
    CacheService.bump_version("organic_content", request.user.id)
    if result.get("success"):
        message = f"Organik içerik senkronize edildi: {result.get('created', 0)} yeni, {result.get('updated', 0)} güncel kayıt."
        if wants_json:
            return JsonResponse({
                "success": True,
                "message": message,
                "created": result.get("created", 0),
                "updated": result.get("updated", 0),
                "metrics": result.get("metrics", 0),
                "fetched": result.get("fetched", 0),
            })
        messages.success(request, message)
    else:
        message = result.get("error") or "Organik içerik senkronizasyonu tamamlanamadı."
        if wants_json:
            return JsonResponse({"success": False, "message": message}, status=400)
        messages.error(request, message)
    return redirect("organic_connections")


@login_required
def organic_content_publish(request, post_id):
    if request.method != "POST":
        return redirect("organic_content_center")

    labels = _request_labels(request)
    account_ids = list(_accessible_platform_accounts(request.user).values_list("id", flat=True))
    post = get_object_or_404(
        SocialPost,
        Q(user=request.user) | Q(platform_account_id__in=account_ids),
        id=post_id,
    )
    result = publish_post(post)
    CacheService.bump_version("reports_center", request.user.id)
    CacheService.bump_version("organic_content", request.user.id)
    if result.success:
        messages.success(request, result.message)
    else:
        messages.error(request, result.message)
    return redirect("organic_content_center")
