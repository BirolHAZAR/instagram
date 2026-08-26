from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import (
    Ad,
    AdMetricHistory,
    BudgetOptimizationRule,
    BudgetOptimizationLog,
    Platform,
    PlatformAccount,
)
try:
    from core.services.notification_helper import NotificationHelper
except Exception:
    NotificationHelper = None
from core.services.performance_metrics import aggregate_metric_queryset
from core.services.agency_scope import get_agency_scope, scope_queryset
from core.services.ad_budget import current_budget_for_ad
from core.views.ads_center import _date_range_from_request


def _to_decimal(value, default="0"):
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _money_from_raw(raw_data, keys):
    if not isinstance(raw_data, dict):
        return None
    for key in keys:
        value = raw_data.get(key)
        if value not in (None, ""):
            return _to_decimal(value)
    return None


def _current_budget_for_ad(ad):
    return current_budget_for_ad(ad)[0]


def _metric_summary(ad, start_date=None, end_date=None):
    qs = AdMetricHistory.objects.filter(ad=ad)
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)
    totals = aggregate_metric_queryset(qs)
    spend = _to_decimal(totals.get("spend"))
    value = _to_decimal(totals.get("conversion_value"))
    roas = _to_decimal(totals.get("roas"))
    return {
        "spend": spend,
        "impressions": totals.get("impressions") or 0,
        "clicks": totals.get("clicks") or 0,
        "conversions": _to_decimal(totals.get("conversions")),
        "conversion_value": value,
        "roas": roas,
        "ctr": _to_decimal(totals.get("ctr")),
        "cpc": _to_decimal(totals.get("cpc")),
    }


def _decision_for_ad(ad, rule, start_date=None, end_date=None):
    metrics = _metric_summary(ad, start_date, end_date)
    current_budget = _current_budget_for_ad(ad)
    target_roas = _to_decimal(rule.roas_target if rule else 2)
    step = _to_decimal(rule.adjustment_step if rule else 5)
    min_budget = _to_decimal(rule.min_budget if rule else 0)
    max_budget = _to_decimal(rule.max_budget if rule else current_budget + step)

    spend = metrics["spend"]
    roas = metrics["roas"]

    if current_budget <= 0:
        current_budget = min_budget if min_budget > 0 else step

    if spend <= 0:
        new_budget = current_budget
        action = "WAIT"
        reason = "Yeterli harcama verisi oluşmadığı için bütçe değişikliği önerilmedi."
        confidence = 55
    elif roas >= target_roas:
        new_budget = min(max_budget, current_budget + step)
        action = "INCREASE" if new_budget > current_budget else "KEEP"
        reason = f"ROAS hedefin üzerinde. Hedef: {target_roas:.2f}x, gerçekleşen: {roas:.2f}x."
        confidence = 86
    else:
        new_budget = max(min_budget, current_budget - step)
        action = "DECREASE" if new_budget < current_budget else "KEEP"
        reason = f"ROAS hedefin altında. Hedef: {target_roas:.2f}x, gerçekleşen: {roas:.2f}x."
        confidence = 78

    return {
        "old_budget": current_budget.quantize(Decimal("0.01")),
        "new_budget": new_budget.quantize(Decimal("0.01")),
        "action": action,
        "reason": reason,
        "confidence": confidence,
        "metrics": metrics,
    }


def _platform_code(ad):
    if getattr(ad, "platform_account", None) and ad.platform_account.platform:
        return ad.platform_account.platform.code
    if getattr(ad, "platform_connection", None) and ad.platform_connection.platform:
        return ad.platform_connection.platform.code
    return "unknown"


def _action_label(action):
    return {
        "INCREASE": "Bütçe artır",
        "DECREASE": "Bütçe azalt",
        "KEEP": "Sabit tut",
        "WAIT": "Veri bekle",
    }.get(action, "Analiz et")


def _action_class(action):
    return {
        "INCREASE": "success",
        "DECREASE": "warning",
        "KEEP": "info",
        "WAIT": "muted",
    }.get(action, "muted")


def _platform_live_budget_supported():
    """Şu an projede gerçek platform bütçe güncelleme adaptörü yok.

    Bu fonksiyon özellikle False döner; böylece kullanıcı canlıya uygula seçse bile
    sistem güvenli şekilde sadece öneri/log oluşturur. Platform API bütçe güncelleme
    servisleri eklenince burada destek kontrolü açılabilir.
    """
    return False


@login_required
def optimizasyon_kurallari(request):
    rules_page = request.resolver_match.url_name == "optimizasyon_kurallari"
    agency_scope = get_agency_scope(request)
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    start_date, end_date = _date_range_from_request(request)
    if request.method == "POST":
        if "finish_optimization" in request.POST:
            request.session.pop("budget_optimized_ids", None)
            request.session.pop("budget_optimized_mode", None)
            if is_ajax:
                return JsonResponse({"success": True, "message": "İptal edildi."})
            messages.success(request, "Optimizasyon seçim modu kapatıldı. Kartlar normal görünüme döndü.")
            return redirect("budget_optimization")

        if "create_rule" in request.POST:
            platform = get_object_or_404(Platform, id=request.POST.get("platform"))
            BudgetOptimizationRule.objects.create(
                user=request.user,
                platform=platform,
                name=request.POST.get("name", "Yeni Kural").strip(),
                min_budget=_to_decimal(request.POST.get("min_budget")),
                max_budget=_to_decimal(request.POST.get("max_budget")),
                adjustment_step=_to_decimal(request.POST.get("adjustment_step"), "5"),
                roas_target=float(request.POST.get("roas_target") or 2),
                lookback_hours=int(request.POST.get("lookback_hours") or 24),
                is_active=True,
            )
            messages.success(request, "Optimizasyon kuralı oluşturuldu.")
            return redirect("optimizasyon_kurallari")

        if "update_rule" in request.POST:
            rule = get_object_or_404(BudgetOptimizationRule, id=request.POST.get("rule_id"), user=request.user)
            rule.platform = get_object_or_404(Platform, id=request.POST.get("platform"))
            rule.name = request.POST.get("name", rule.name).strip()
            rule.min_budget = _to_decimal(request.POST.get("min_budget"))
            rule.max_budget = _to_decimal(request.POST.get("max_budget"))
            rule.adjustment_step = _to_decimal(request.POST.get("adjustment_step"), "5")
            rule.roas_target = float(request.POST.get("roas_target") or 2)
            rule.lookback_hours = int(request.POST.get("lookback_hours") or 24)
            rule.is_active = request.POST.get("is_active", "on") == "on"
            rule.save()
            messages.success(request, "Optimizasyon kuralı güncellendi.")
            return redirect("optimizasyon_kurallari")

        if "delete_rule" in request.POST:
            rule = get_object_or_404(BudgetOptimizationRule, id=request.POST.get("rule_id"), user=request.user)
            rule.delete()
            messages.success(request, "Optimizasyon kuralı silindi.")
            return redirect("optimizasyon_kurallari")

        if "optimize_selected_ads" in request.POST:
            selected_ids = request.POST.getlist("selected_ads")
            rule_id = request.POST.get("selected_rule")

            if not selected_ids:
                messages.warning(request, "Optimizasyon başlatmak için en az bir reklam seçmelisin.")
                return redirect("optimizasyon_kurallari")

            rule = BudgetOptimizationRule.objects.filter(id=rule_id, user=request.user, is_active=True).first()
            if not rule:
                messages.warning(request, "Önce aktif bir optimizasyon kuralı seçmelisin.")
                return redirect("optimizasyon_kurallari")

            ads = scope_queryset(
                request,
                Ad.objects.filter(id__in=selected_ids, source_type="OWN"),
            ).select_related(
                "campaign", "ad_group", "creative", "platform_account", "platform_account__platform",
                "platform_connection", "platform_connection__platform",
            )

            created_count = 0
            increase_count = 0
            decrease_count = 0
            keep_count = 0
            total_delta = Decimal("0")
            optimized_ids = []

            for ad in ads:
                decision = _decision_for_ad(ad, rule, start_date, end_date)
                delta = decision["new_budget"] - decision["old_budget"]
                total_delta += delta
                if decision["action"] == "INCREASE":
                    increase_count += 1
                elif decision["action"] == "DECREASE":
                    decrease_count += 1
                else:
                    keep_count += 1

                # Güvenli profesyonel davranış: reel ROI/ROAS hesabına göre aksiyon üretilir,
                # ama platform bütçesi otomatik değiştirilmez. Üye kendi reklam panelinde manuel uygular.
                BudgetOptimizationLog.objects.create(
                    user=request.user,
                    reklam=ad,
                    platform_code=_platform_code(ad),
                    rule=rule,
                    old_budget=decision["old_budget"],
                    new_budget=decision["new_budget"],
                    reason=decision["reason"],
                    ai_confidence=decision["confidence"],
                    success=True,
                    performance_data={
                        "action": decision["action"],
                        "apply_mode": "manual_review",
                        "live_apply_supported": False,
                        "live_apply_executed": False,
                        "manual_required": True,
                        "note": "ROI/ROAS hesabına göre manuel uygulanacak bütçe aksiyonu oluşturuldu. Platform bütçesi otomatik değiştirilmedi.",
                        "spend": str(decision["metrics"]["spend"]),
                        "roas": str(decision["metrics"]["roas"].quantize(Decimal("0.01"))),
                        "ctr": str(decision["metrics"]["ctr"]),
                        "clicks": decision["metrics"]["clicks"],
                        "impressions": decision["metrics"]["impressions"],
                    },
                )
                optimized_ids.append(str(ad.id))
                created_count += 1

            optimized_id_set = set(optimized_ids)
            optimized_ids = [str(ad_id) for ad_id in selected_ids if str(ad_id) in optimized_id_set]
            request.session["budget_optimized_ids"] = optimized_ids
            request.session["budget_optimized_mode"] = "active"

            msg = "Oluşturuldu."
            if not is_ajax:
                messages.success(request, msg)
            if NotificationHelper:
                NotificationHelper.notify(
                    request.user,
                    "Bütçe optimizasyonu oluşturuldu",
                    msg,
                    level="success",
                    icon="💰",
                    link="/optimizasyon-gecmisi/",
                    dedupe_minutes=0,
                )
            if is_ajax:
                return JsonResponse({"success": True, "message": msg, "optimized_ids": optimized_ids})
            return redirect("budget_optimization")

    rules = BudgetOptimizationRule.objects.filter(user=request.user).select_related("platform").order_by("-is_active", "name")
    platforms = Platform.objects.all().order_by("name")
    active_rule = rules.filter(is_active=True).first()

    ads_qs = scope_queryset(
        request,
        Ad.objects.filter(source_type="OWN", is_active=True),
    ).select_related(
        "campaign", "ad_group", "creative", "platform_account", "platform_account__platform",
        "platform_connection", "platform_connection__platform",
    ).order_by("-updated_at")[:120]

    optimized_order = [str(value) for value in request.session.get("budget_optimized_ids", [])]
    locked_ids = set(optimized_order)
    optimized_rank = {ad_id: index for index, ad_id in enumerate(optimized_order)}
    ad_cards = []
    for natural_rank, ad in enumerate(ads_qs):
        metrics = _metric_summary(ad, start_date, end_date)
        current_budget = _current_budget_for_ad(ad)
        decision = _decision_for_ad(ad, active_rule, start_date, end_date)
        roas = metrics["roas"]
        action = decision["action"]

        if metrics["spend"] <= 0:
            health = "Veri Bekliyor"
            health_class = "muted"
        elif action == "INCREASE":
            health = "Yüksek Performans"
            health_class = "success"
        elif action == "DECREASE":
            health = "Düşük Performans"
            health_class = "warning"
        elif action == "KEEP":
            health = "Sabit Tut"
            health_class = "info"
        else:
            health = "Kontrol"
            health_class = "muted"

        # Aksiyon gereken: gerçek bütçe değişimi gerektiren kartlar.
        # ÖNEMLİ: Sayfa ilk açıldığında bütçe alanı yanıp sönmez.
        # Pulse sadece kullanıcı Optimize Et dedikten sonra, session'da kilitlenen kartlarda görünür.
        suggested = action in ("INCREASE", "DECREASE") and decision["new_budget"] != decision["old_budget"]
        is_locked = str(ad.id) in locked_ids
        if is_locked and action == "INCREASE" and suggested:
            budget_pulse_class = "increase"
            budget_signal_label = "Optimizasyon aktif"
        elif is_locked and action == "DECREASE" and suggested:
            budget_pulse_class = "decrease"
            budget_signal_label = "Optimizasyon aktif"
        elif is_locked:
            budget_pulse_class = "active"
            budget_signal_label = "Optimizasyon aktif"
        else:
            budget_pulse_class = "normal"
            budget_signal_label = ""

        platform_name = "Platform yok"
        platform_code = "unknown"
        if getattr(ad, "platform_account", None) and ad.platform_account.platform:
            platform_name = ad.platform_account.platform.name
            platform_code = ad.platform_account.platform.code
        elif getattr(ad, "platform_connection", None) and ad.platform_connection.platform:
            platform_name = ad.platform_connection.platform.name
            platform_code = ad.platform_connection.platform.code

        ad_id_str = str(ad.id)
        ad_cards.append({
            "id": ad.id,
            "id_str": ad_id_str,
            "name": ad.name or ad.headline or f"Reklam #{ad.id}",
            "campaign": ad.campaign.name if ad.campaign else "Kampanya yok",
            "ad_group": ad.ad_group.name if ad.ad_group else "Reklam grubu yok",
            "platform_name": platform_name,
            "platform_code": platform_code,
            "status": ad.status,
            "image": ad.preview_image_url or (ad.creative.thumbnail_url if ad.creative else None) or (ad.creative.image_url if ad.creative else None),
            "budget": current_budget,
            "budget_type": current_budget_for_ad(ad)[1],
            "spend": metrics["spend"],
            "roas": roas,
            "ctr": metrics["ctr"],
            "cpc": metrics["cpc"],
            "clicks": metrics["clicks"],
            "impressions": metrics["impressions"],
            "conversions": metrics["conversions"],
            "conversion_value": metrics["conversion_value"],
            "has_revenue_data": metrics["conversion_value"] > 0,
            "old_budget": decision["old_budget"],
            "new_budget": decision["new_budget"],
            "budget_delta": decision["new_budget"] - decision["old_budget"],
            "budget_pulse_class": budget_pulse_class,
            "budget_signal_label": budget_signal_label,
            "decision_reason": decision["reason"],
            "action": action,
            "action_label": _action_label(action),
            "action_class": _action_class(action),
            "health": health,
            "health_class": health_class,
            "suggested": suggested,
            "is_locked": is_locked,
            "optimized_rank": optimized_rank.get(str(ad.id), 999999),
            "natural_rank": natural_rank,
        })

    # Son optimize edilen kartlar sayfanın başına gelsin.
    ad_cards.sort(key=lambda item: (
        not item["is_locked"],
        item["optimized_rank"] if item["is_locked"] else item["natural_rank"],
    ))

    total_budget = sum((card["budget"] for card in ad_cards), Decimal("0"))
    total_spend = sum((card["spend"] for card in ad_cards), Decimal("0"))
    total_conversion_value = sum((card["conversion_value"] for card in ad_cards), Decimal("0"))
    # Ortalama ROAS kartı sıfır görünmesin diye basit ortalama yerine toplam dönüşüm değeri / toplam harcama kullanılır.
    # Harcama yoksa 0 gösterilir; yanlış uydurma değer basılmaz.
    avg_roas = (total_conversion_value / total_spend) if total_spend > 0 else Decimal("0")
    suggested_count = sum(1 for card in ad_cards if card["suggested"])

    context = {
        "rules_page": rules_page,
        "agency_scope": agency_scope,
        "metric_start_date": start_date,
        "metric_end_date": end_date,
        "rules": rules,
        "platforms": platforms,
        "ad_cards": ad_cards,
        "total_ads": len(ad_cards),
        "suggested_count": suggested_count,
        "total_budget": total_budget,
        "total_spend": total_spend,
        "avg_roas": avg_roas,
        "avg_roas_available": total_conversion_value > 0 and total_spend > 0,
        "active_rule": active_rule,
        "optimized_mode": bool(locked_ids),
        "live_budget_supported": _platform_live_budget_supported(),
        "v2_only": True,
    }
    return render(request, "budget_optimization/optimizasyon_kurallari.html", context)


@login_required
def budget_sunum(request):
    return render(request, "budget_optimization/sunum.html", {"v2_only": True})


@login_required
def optimization_history(request):
    """Optimizasyon geçmişi.

    Eski sayfanın mantığını korur: her reklam bir satırdır, satıra tıklanınca
    o reklama ait geçmiş optimizasyon kayıtları açılır. Yeni yapılan manuel
    optimizasyon logları BudgetOptimizationLog üzerinden okunur.
    """
    platform = request.GET.get("platform", "").strip()
    account_id = request.GET.get("account_id", "").strip()
    search = request.GET.get("search", "").strip()

    logs_qs = BudgetOptimizationLog.objects.filter(user=request.user).select_related(
        "reklam",
        "reklam__campaign",
        "reklam__ad_group",
        "reklam__platform_account",
        "reklam__platform_account__platform",
        "rule",
        "rule__platform",
    ).order_by("-created_at")

    if platform:
        logs_qs = logs_qs.filter(platform_code__iexact=platform)
    if account_id:
        logs_qs = logs_qs.filter(reklam__platform_account_id=account_id)
    if search:
        logs_qs = logs_qs.filter(reklam__name__icontains=search)

    logs = list(logs_qs[:500])

    # Eski history.html mantığı: reklam bazında tek satır, altında geçmiş detayları.
    grouped = {}
    total_delta = Decimal("0")
    increase_count = 0
    decrease_count = 0
    keep_count = 0
    success_count = 0

    for log in logs:
        reklam = getattr(log, "reklam", None)
        if not reklam:
            continue

        old_budget = _to_decimal(log.old_budget)
        new_budget = _to_decimal(log.new_budget)
        delta = new_budget - old_budget
        total_delta += delta

        if delta > 0:
            trend = "up"
            increase_count += 1
        elif delta < 0:
            trend = "down"
            decrease_count += 1
        else:
            trend = "same"
            keep_count += 1

        if log.success:
            success_count += 1

        rid = reklam.id
        if rid not in grouped:
            platform_name = log.platform_code
            if getattr(reklam, "platform_account", None) and reklam.platform_account.platform:
                platform_name = reklam.platform_account.platform.name or log.platform_code

            grouped[rid] = {
                "reklam": reklam,
                "last_log": log,
                "trend": trend,
                "platform_name": platform_name,
                "logs": [],
                "log_count": 0,
                "total_delta": Decimal("0"),
            }

        grouped[rid]["logs"].append(log)
        grouped[rid]["log_count"] += 1
        grouped[rid]["total_delta"] += delta

    reklam_list = list(grouped.values())
    # En güncel optimizasyon en üstte olacak şekilde sıralama.
    reklam_list.sort(key=lambda item: item["last_log"].created_at, reverse=True)

    # Yeni template kullanırsa diye log_rows da korunur.
    log_rows = []
    for log in logs:
        reklam = getattr(log, "reklam", None)
        old_budget = _to_decimal(log.old_budget)
        new_budget = _to_decimal(log.new_budget)
        delta = new_budget - old_budget
        if delta > 0:
            action = "INCREASE"
        elif delta < 0:
            action = "DECREASE"
        else:
            action = "KEEP"
        perf = log.performance_data if isinstance(log.performance_data, dict) else {}
        log_rows.append({
            "id": log.id,
            "created_at": log.created_at,
            "ad": reklam,
            "ad_name": getattr(reklam, "name", None) or f"Reklam #{getattr(reklam, 'id', '')}",
            "campaign": getattr(getattr(reklam, "campaign", None), "name", "Kampanya yok"),
            "ad_group": getattr(getattr(reklam, "ad_group", None), "name", "Reklam grubu yok"),
            "platform_code": log.platform_code,
            "rule_name": getattr(log.rule, "name", "Kural yok"),
            "old_budget": old_budget,
            "new_budget": new_budget,
            "delta": delta,
            "action": action,
            "action_label": _action_label(action),
            "action_class": _action_class(action),
            "reason": log.reason,
            "success": log.success,
            "confidence": log.ai_confidence,
            "roas": perf.get("roas", "0"),
            "spend": perf.get("spend", "0"),
            "manual_required": perf.get("manual_required", True),
            "apply_mode": perf.get("apply_mode", "manual_review"),
        })

    platforms = BudgetOptimizationLog.objects.filter(user=request.user).exclude(platform_code="").values_list("platform_code", flat=True).distinct().order_by("platform_code")
    accounts = PlatformAccount.objects.filter(user=request.user, is_active=True).select_related("platform").order_by("platform__name", "account_name")

    context = {
        "reklam_list": reklam_list,
        "log_rows": log_rows,
        "logs": logs,
        "platforms": [{"code": p, "name": str(p).upper()} for p in platforms if p],
        "accounts": accounts,
        "selected_platform": platform,
        "selected_account": account_id,
        "search_query": search,
        "total_logs": len(logs),
        "total_reklams": len(reklam_list),
        "increase_count": increase_count,
        "decrease_count": decrease_count,
        "keep_count": keep_count,
        "success_count": success_count,
        "total_delta": total_delta,
        "v2_only": True,
    }
    return render(request, "budget_optimization/history.html", context)

@login_required
def apply_rules_to_campaigns(request):
    messages.info(request, "Bütçe optimizasyonu için reklamları seçip kural belirleyerek işlemi başlatabilirsin.")
    return redirect("optimizasyon_kurallari")


@login_required
def ajax_get_reklams(request):
    qs = Ad.objects.filter(user=request.user, source_type="OWN").select_related("platform_account", "platform_account__platform")
    data = []
    for ad in qs[:200]:
        metrics = _metric_summary(ad)
        data.append({
            "id": ad.id,
            "name": str(ad),
            "platform": _platform_code(ad),
            "spend": float(metrics["spend"]),
            "conversions": float(metrics["conversions"]),
            "roas": float(metrics["roas"]),
        })
    return JsonResponse({"success": True, "reklams": data, "ads": data})


@login_required
@require_POST
def ajax_optimize_reklam(request):
    ad_id = request.POST.get("reklam_id") or request.POST.get("ad_id")
    rule_id = request.POST.get("rule_id")
    ad = Ad.objects.filter(id=ad_id, user=request.user, source_type="OWN").first()
    if not ad:
        return JsonResponse({"success": False, "message": "Reklam bulunamadı."}, status=404)
    rule = BudgetOptimizationRule.objects.filter(id=rule_id, user=request.user).first()
    decision = _decision_for_ad(ad, rule)
    log = BudgetOptimizationLog.objects.create(
        user=request.user,
        reklam=ad,
        platform_code=_platform_code(ad),
        rule=rule,
        old_budget=decision["old_budget"],
        new_budget=decision["new_budget"],
        reason=decision["reason"],
        ai_confidence=decision["confidence"],
        success=True,
        performance_data={"action": decision["action"], "apply_mode": "manual_review", "live_apply_executed": False},
    )
    return JsonResponse({"success": True, "log_id": log.id, "message": "Bütçe optimizasyon önerisi oluşturuldu."})


@login_required
@require_POST
def ajax_remove_reklam(request):
    ad_id = str(request.POST.get("reklam_id") or request.POST.get("ad_id") or "").strip()
    optimized_ids = [str(value) for value in request.session.get("budget_optimized_ids", [])]
    if ad_id not in optimized_ids:
        return JsonResponse({"success": False, "message": "Reklam aktif optimizasyon listesinde bulunamadı."}, status=404)

    optimized_ids.remove(ad_id)
    if optimized_ids:
        request.session["budget_optimized_ids"] = optimized_ids
        request.session["budget_optimized_mode"] = "active"
    else:
        request.session.pop("budget_optimized_ids", None)
        request.session.pop("budget_optimized_mode", None)

    return JsonResponse({
        "success": True,
        "removed_id": ad_id,
        "remaining_count": len(optimized_ids),
        "message": "İptal edildi.",
    })


@login_required
def ajax_update_selection(request):
    return JsonResponse({"success": True})


@login_required
def ajax_get_reklams_simple(request):
    return ajax_get_reklams(request)


@login_required
def ajax_get_accounts(request):
    accounts = PlatformAccount.objects.filter(user=request.user, is_active=True).select_related("platform")
    return JsonResponse({"success": True, "accounts": [{"id": a.id, "name": a.account_name or a.account_id, "platform": a.platform.code} for a in accounts]})
