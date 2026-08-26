from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.apps import apps

from core.services.agency_scope import get_agency_scope, scope_queryset


def _model(name):
    try:
        return apps.get_model("core", name)
    except LookupError:
        return None


def _field(model, *names):
    if not model:
        return None

    model_fields = {f.name for f in model._meta.get_fields()}

    for name in names:
        if name in model_fields:
            return name

    return None


def _value(obj, *names, default=""):
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


STATUS_LABELS = {
    "ACTIVE": "Aktif",
    "ENABLED": "Aktif",
    "PAUSED": "Duraklatıldı",
    "DISABLED": "Devre dışı",
    "ARCHIVED": "Arşivlendi",
    "DELETED": "Silindi",
    "UNKNOWN": "Bilinmiyor",
}

STRATEGY_LABELS = {
    "CONVERSIONS": "Dönüşümler",
    "LINK_CLICKS": "Bağlantı tıklamaları",
    "LANDING_PAGE_VIEWS": "Açılış sayfası görüntüleme",
    "IMPRESSIONS": "Gösterimler",
    "REACH": "Erişim",
    "LEAD_GENERATION": "Potansiyel müşteri",
    "VALUE": "Dönüşüm değeri",
    "LOWEST_COST_WITHOUT_CAP": "En düşük maliyet",
    "LOWEST_COST_WITH_BID_CAP": "Teklif sınırıyla düşük maliyet",
    "COST_CAP": "Maliyet sınırı",
    "BID_CAP": "Teklif sınırı",
}


@login_required
def adgroup_center(request):
    agency_scope = get_agency_scope(request)
    Campaign = _model("Campaign")
    AdGroup = _model("AdGroup")
    Ad = _model("Ad")

    adgroups = []

    if AdGroup:
        qs = scope_queryset(
            request,
            AdGroup.objects.all(),
            account_lookup="campaign__platform_account",
        ).select_related("campaign", "campaign__platform_account", "campaign__platform_account__platform").order_by("-id")

        campaign_field = _field(AdGroup, "campaign")
        name_field = _field(AdGroup, "name", "adgroup_name", "adset_name")
        external_id_field = _field(AdGroup, "external_id", "adgroup_id", "adset_id", "platform_adgroup_id")
        status_field = _field(AdGroup, "status", "effective_status")
        budget_field = _field(AdGroup, "budget", "daily_budget", "lifetime_budget")
        bid_strategy_field = _field(AdGroup, "bid_strategy", "optimization_goal")
        created_field = _field(AdGroup, "created_at", "created_time", "start_time")

        total_adgroups = qs.count()

        for group in qs[:150]:
            campaign = getattr(group, campaign_field, None) if campaign_field else None
            account = getattr(campaign, "account", None) if campaign else None
            if not account and campaign:
                account = getattr(campaign, "platform_account", None)

            platform = None
            if campaign:
                platform = getattr(campaign, "platform", None)
            if not platform and account:
                platform = getattr(account, "platform", None)

            ad_count = 0
            if Ad:
                try:
                    ad_group_field = _field(Ad, "ad_group", "adgroup", "adset")
                    if ad_group_field:
                        ad_count = Ad.objects.filter(**{ad_group_field: group}).count()
                except Exception:
                    ad_count = 0

            raw_status = str(_value(group, status_field, default="UNKNOWN") if status_field else "UNKNOWN").upper()
            raw_strategy = str(_value(group, bid_strategy_field, default="-") if bid_strategy_field else "-").upper()

            adgroups.append({
                "id": group.id,
                "name": _value(group, name_field, default=f"Reklam Grubu #{group.id}") if name_field else f"Reklam Grubu #{group.id}",
                "external_id": _value(group, external_id_field, default="-") if external_id_field else "-",
                "status": STATUS_LABELS.get(raw_status, raw_status.replace("_", " ").title()),
                "status_key": raw_status.lower(),
                "budget": _value(group, budget_field, default=0) if budget_field else 0,
                "bid_strategy": STRATEGY_LABELS.get(raw_strategy, raw_strategy.replace("_", " ").title()),
                "campaign_name": _value(campaign, "name", "campaign_name", default="-") if campaign else "-",
                "platform_name": getattr(platform, "name", "-") if platform else "-",
                "account_name": _value(account, "name", "account_name", "username", default="-") if account else "-",
                "ad_count": ad_count,
                "created_at": _value(group, created_field, default=None) if created_field else None,
            })

    scoped_campaigns = scope_queryset(request, Campaign.objects.all()) if Campaign else None
    scoped_ads = scope_queryset(request, Ad.objects.filter(source_type="OWN")) if Ad else None

    context = {
        "agency_scope": agency_scope,
        "adgroups": adgroups,
        "total_adgroups": total_adgroups if AdGroup else 0,
        "total_campaigns": scoped_campaigns.count() if scoped_campaigns is not None else 0,
        "total_ads": scoped_ads.count() if scoped_ads is not None else 0,
    }

    return render(request, "reports/adgroup_center.html", context)
