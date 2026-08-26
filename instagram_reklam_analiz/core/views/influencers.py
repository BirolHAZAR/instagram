from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from core.models import Influencer, Platform
from core.models.influencer import normalize_influencer_handle
from core.services.cache_service import CacheService
from core.services.influencer_service import (
    CACHE_NAMESPACE,
    influencer_cache_version,
    influencer_queryset,
    influencer_stats,
    invalidate_influencer_cache,
    snapshot_influencer_metrics,
)


def influencer_discovery(request):
    filters = {
        "q": request.GET.get("q", ""),
        "platform": request.GET.get("platform", ""),
        "category": request.GET.get("category", ""),
        "country": request.GET.get("country", ""),
        "min_followers": request.GET.get("min_followers", ""),
        "min_engagement": request.GET.get("min_engagement", ""),
    }
    cache_identity = request.user.id if request.user.is_authenticated else "public"
    version = influencer_cache_version(cache_identity)
    cache_key_parts = [
        "stats",
        cache_identity,
        filters["q"],
        filters["platform"],
        filters["category"],
        filters["country"],
        filters["min_followers"],
        filters["min_engagement"],
    ]

    qs = influencer_queryset(filters)
    paginator = Paginator(qs, 24)
    page_obj = paginator.get_page(request.GET.get("page"))
    stats = CacheService.get(CACHE_NAMESPACE, *cache_key_parts, version=version)
    if stats is None:
        stats = influencer_stats(qs)
        CacheService.set(CACHE_NAMESPACE, *cache_key_parts, value=stats, timeout=180, version=version)
    context = {
        "influencers": page_obj.object_list,
        "page_obj": page_obj,
        "stats": stats,
        "platforms": Platform.objects.filter(is_active=True).order_by("name"),
        "categories": Influencer.CATEGORY_CHOICES,
        "filters": filters,
    }
    return render(request, "influencers/discovery.html", context)


def influencer_detail(request, influencer_id):
    influencer = get_object_or_404(
        Influencer.objects.select_related("platform", "created_by"),
        id=influencer_id,
        is_active=True,
    )
    history = influencer.metric_history.order_by("-date")[:60]
    return render(request, "influencers/detail.html", {
        "influencer": influencer,
        "history": history,
    })


@login_required
def influencer_add(request):
    if request.method != "POST":
        return redirect("influencer_discovery")

    platform_id = request.POST.get("platform")
    platform = Platform.objects.filter(id=platform_id, is_active=True).first()
    handle = request.POST.get("handle", "").strip()
    normalized = normalize_influencer_handle(handle)
    if not platform or not normalized:
        messages.error(request, "Platform ve kullanıcı adı zorunlu.")
        return redirect("influencer_discovery")

    existing = Influencer.objects.filter(platform=platform, normalized_handle=normalized).first()
    if existing:
        messages.info(request, f"{existing.display_name} zaten kayıtlı. Mevcut kayda yönlendirildin.")
        return redirect("influencer_detail", influencer_id=existing.id)

    influencer = Influencer.objects.create(
        platform=platform,
        handle=handle if handle.startswith("@") else f"@{normalized}",
        normalized_handle=normalized,
        display_name=request.POST.get("display_name", "").strip() or handle or normalized,
        category=request.POST.get("category") or "other",
        country=request.POST.get("country", "").strip() or None,
        city=request.POST.get("city", "").strip() or None,
        language=request.POST.get("language", "").strip() or None,
        follower_count=_int_value(request.POST.get("follower_count")),
        avg_likes=_int_value(request.POST.get("avg_likes")),
        avg_comments=_int_value(request.POST.get("avg_comments")),
        avg_views=_int_value(request.POST.get("avg_views")),
        engagement_rate=_decimal_value(request.POST.get("engagement_rate")),
        estimated_reach=_int_value(request.POST.get("estimated_reach")),
        contact_email=request.POST.get("contact_email", "").strip() or None,
        notes=request.POST.get("notes", "").strip() or None,
        source="manual",
        created_by=request.user,
    )
    snapshot_influencer_metrics(influencer)
    invalidate_influencer_cache(request.user.id)
    messages.success(request, f"{influencer.display_name} influencer havuzuna eklendi.")
    return redirect("influencer_detail", influencer_id=influencer.id)


def _int_value(value) -> int:
    try:
        return max(int(str(value or "0").replace(".", "").replace(",", "")), 0)
    except (TypeError, ValueError):
        return 0


def _decimal_value(value) -> Decimal:
    try:
        return max(Decimal(str(value or "0").replace(",", ".")), Decimal("0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
