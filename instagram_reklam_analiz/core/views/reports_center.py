from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import render

from core.models import Ad, AdMetricHistory, Platform, PlatformAccount
from core.services.cache_service import CacheService
from core.services.agency_scope import get_agency_scope, platform_accounts_for_request, scope_queryset
from core.services.organic_content_service import organic_summary_for_user
from core.services.performance_metrics import aggregate_metric_queryset


REPORTS_CENTER_CACHE_TIMEOUT = 180


def _organic_report_recommendation(organic_stats, organic_engagement_share):
    if not organic_stats["total_posts"]:
        return "Organik veri yok. Rapor etkisini gormek icin gercek organik hesap baglantisi ve senkronizasyon gerekli."
    if organic_engagement_share >= 35:
        return "Organik icerik guclu sinyal uretiyor; en yuksek etkilesimli postlar reklam kreatifine donusturulmeli."
    if organic_stats["draft_posts"] > organic_stats["published_posts"]:
        return "Taslak havuzu genis; yayin takvimi tamamlanirsa organik katkisi raporlarda daha gorunur olur."
    return "Organik kanal rapora ek destek veriyor; reklam ve organik kreatifleri birlikte test etmek faydali olur."


def _get_sort_field(sort_by):
    allowed = {
        "-created_at": "-created_at",
        "created_at": "created_at",
        "name": "name",
        "-name": "-name",
        "status": "status",
        "-status": "-status",
        "-total_impressions": "-total_impressions",
        "-total_clicks": "-total_clicks",
        "-total_spend": "-total_spend",
        "-avg_ctr": "-avg_ctr",
        "-avg_engagement_rate": "-avg_engagement_rate",
    }
    return allowed.get(sort_by, "-created_at")


@login_required
def reports_center(request):
    user = request.user
    agency_scope = get_agency_scope(request)

    search_query = request.GET.get("arama", "").strip()
    platform_code = request.GET.get("platform", "")
    account_id = request.GET.get("hesap", "")
    start_date_str = request.GET.get("baslangic_tarih", "")
    end_date_str = request.GET.get("bitis_tarih", "")
    status_filter = request.GET.get("durum", "").strip().upper()
    sort_by = _get_sort_field(request.GET.get("sirala", "-created_at"))
    version = CacheService.get_version("reports_center", user.id)
    cache_key_parts = (
        "v2",
        "user",
        user.id,
        "agency_client",
        agency_scope.cache_key,
        "arama",
        search_query or "all",
        "platform",
        platform_code or "all",
        "hesap",
        account_id or "all",
        "baslangic",
        start_date_str or "all",
        "bitis",
        end_date_str or "all",
        "durum",
        status_filter or "all",
        "sirala",
        sort_by,
    )
    cached_context = CacheService.get("reports_center", *cache_key_parts, version=version)
    if cached_context is not None:
        return render(request, "reklamlar/reklam_raporu.html", cached_context)

    start_date = None
    end_date = None

    ads = (
        scope_queryset(request, Ad.objects.filter(source_type="OWN"))
        .select_related(
            "platform_account",
            "platform_account__platform",
            "campaign",
            "ad_group",
            "creative",
        )
        .annotate(
            total_impressions=Sum("metric_history__impressions"),
            total_clicks=Sum("metric_history__clicks"),
            total_spend=Sum("metric_history__spend"),
            total_conversions=Sum("metric_history__conversions"),
            avg_ctr=Avg("metric_history__ctr"),
            avg_cpc=Avg("metric_history__cpc"),
            avg_cpm=Avg("metric_history__cpm"),
            avg_engagement_rate=Avg("metric_history__engagement_rate"),
            total_likes=Sum("metric_history__likes"),
            total_comments=Sum("metric_history__comments"),
            total_shares=Sum("metric_history__shares"),
            total_saves=Sum("metric_history__saves"),
        )
        .distinct()
    )

    if search_query:
        ads = ads.filter(
            Q(name__icontains=search_query)
            | Q(headline__icontains=search_query)
            | Q(primary_text__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(campaign__name__icontains=search_query)
            | Q(ad_group__name__icontains=search_query)
            | Q(creative__title__icontains=search_query)
        )

    if platform_code:
        ads = ads.filter(platform_account__platform__code=platform_code)

    if account_id:
        ads = ads.filter(platform_account_id=account_id)

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            ads = ads.filter(created_at__date__gte=start_date)
        except ValueError:
            pass

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            ads = ads.filter(created_at__date__lte=end_date)
        except ValueError:
            pass

    if status_filter:
        ads = ads.filter(status__iexact=status_filter)

    ads = ads.order_by(sort_by)

    metric_qs = AdMetricHistory.objects.filter(ad__in=ads)
    if start_date:
        metric_qs = metric_qs.filter(date__gte=start_date)
    if end_date:
        metric_qs = metric_qs.filter(date__lte=end_date)
    metric_summary = aggregate_metric_queryset(metric_qs)
    stats = {
        "toplam_reklam": ads.count(),
        "toplam_gosterim": metric_summary.get("impressions") or 0,
        "toplam_tiklama": metric_summary.get("clicks") or 0,
        "toplam_harcama": metric_summary.get("spend") or 0,
        "toplam_donusum": metric_summary.get("conversions") or 0,
        "ortalama_ctr": metric_summary.get("ctr") or 0,
        "ortalama_cpc": metric_summary.get("cpc") or 0,
        "ortalama_cpm": metric_summary.get("cpm") or 0,
        "ortalama_etkilesim": metric_summary.get("engagement_rate") or 0,
        "toplam_begeni": metric_summary.get("likes") or 0,
        "toplam_yorum": metric_summary.get("comments") or 0,
        "toplam_paylasim": metric_summary.get("shares") or 0,
        "toplam_kaydetme": metric_summary.get("saves") or 0,
    }
    scoped_platform_accounts = platform_accounts_for_request(request, active_only=True)
    organic_stats = organic_summary_for_user(user, platform_accounts=scoped_platform_accounts)
    paid_engagement = (
        (stats["toplam_begeni"] or 0)
        + (stats["toplam_yorum"] or 0)
        + (stats["toplam_paylasim"] or 0)
        + (stats["toplam_kaydetme"] or 0)
    )
    blended_engagement = paid_engagement + organic_stats["engagement"]
    paid_reach_proxy = stats["toplam_gosterim"] or 0
    organic_reach_share = (
        round((organic_stats["reach"] / (paid_reach_proxy + organic_stats["reach"])) * 100, 2)
        if paid_reach_proxy or organic_stats["reach"]
        else 0
    )
    organic_engagement_share = (
        round((organic_stats["engagement"] / blended_engagement) * 100, 2)
        if blended_engagement
        else 0
    )

    platforms = list(
        Platform.objects.filter(is_active=True, accounts__in=scoped_platform_accounts)
        .distinct()
        .order_by("name")
    )

    platform_accounts = list(
        scoped_platform_accounts
        .select_related("platform", "connection")
        .order_by("account_name", "account_id")
    )

    ads_list = list(ads)

    context = {
        "reklamlar": ads_list,
        "ads": ads_list,
        "platforms": platforms,
        "platform_accounts": platform_accounts,
        "stats": {
            "toplam_reklam": stats["toplam_reklam"] or 0,
            "toplam_gosterim": stats["toplam_gosterim"] or 0,
            "toplam_tiklama": stats["toplam_tiklama"] or 0,
            "toplam_harcama": stats["toplam_harcama"] or 0,
            "toplam_donusum": stats["toplam_donusum"] or 0,
            "ortalama_ctr": round(stats["ortalama_ctr"] or 0, 2),
            "ortalama_cpc": round(stats["ortalama_cpc"] or 0, 2),
            "ortalama_cpm": round(stats["ortalama_cpm"] or 0, 2),
            "ortalama_etkilesim": round(stats["ortalama_etkilesim"] or 0, 2),
            "toplam_begeni": stats["toplam_begeni"] or 0,
            "toplam_yorum": stats["toplam_yorum"] or 0,
            "toplam_paylasim": stats["toplam_paylasim"] or 0,
            "toplam_kaydetme": stats["toplam_kaydetme"] or 0,
            "toplam_video": 0,
        },
        "organic_stats": organic_stats,
        "organic_report_impact": {
            "paid_engagement": paid_engagement,
            "blended_engagement": blended_engagement,
            "organic_engagement_share": organic_engagement_share,
            "organic_reach_share": organic_reach_share,
            "recommendation": _organic_report_recommendation(organic_stats, organic_engagement_share),
        },
        "filtre_arama": search_query,
        "filtre_platform": platform_code,
        "filtre_hesap": account_id,
        "filtre_baslangic": start_date_str,
        "filtre_bitis": end_date_str,
        "filtre_durum": status_filter.lower(),
        "filtre_sirala": sort_by,
        "agency_scope": agency_scope,
    }
    CacheService.set(
        "reports_center",
        *cache_key_parts,
        value=context,
        timeout=REPORTS_CENTER_CACHE_TIMEOUT,
        version=version,
    )

    return render(request, "reklamlar/reklam_raporu.html", context)
