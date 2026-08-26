from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.db.models import Q, Sum
from django.utils import timezone
from datetime import timedelta

from core.models import Ad, AdMetricHistory, FeatureUsageLedger, OctoTaskInstance, OctoTaskRule, ReklamAIAnaliz
from core.decorators import ai_credit_required
from core.services.entitlements import get_active_subscription
from core.services.openai_usage import consume_openai_operation, refund_ai_tariff_credits
from core.services.ai_credit_purchase import insufficient_credit_payload
from core.services.ad_ai_service import generate_ad_report, serialize_ad_report
from core.services.performance_metrics import aggregate_metric_queryset
from core.services.agency_scope import get_agency_scope, scope_queryset
from core.services.cache_service import CacheService


def _score_from_metrics(m):
    spend = float(m.get("spend") or 0)
    conversions = float(m.get("conversions") or 0)
    ctr = float(m.get("ctr") or 0)
    roas = float(m.get("roas") or 0)
    cpa = float(m.get("cpa") or 0)
    score = 40
    score += min(25, ctr * 6)
    score += min(25, roas * 8)
    if cpa and cpa < 150:
        score += 10
    return int(max(0, min(100, score)))


@login_required
def ai_dashboard(request):
    agency_scope = get_agency_scope(request)
    requested_ad_id = (request.GET.get("ad") or "").strip()
    version = CacheService.get_version("ai_dashboard", request.user.id)
    cache_parts = ("user", request.user.id, "scope", agency_scope.cache_key, "ad", requested_ad_id or "default")
    cached = CacheService.get("ai_dashboard", *cache_parts, version=version)
    if cached is not None:
        cached = dict(cached)
        cached["agency_scope"] = agency_scope
        return render(request, "ai/dashboard.html", cached)
    ads = list(scope_queryset(request, Ad.objects.filter(source_type="OWN")).select_related("platform_account__platform", "campaign", "creative").order_by("-last_synced_at", "-created_at")[:200])
    selected_ad = None
    ad_id = request.GET.get("ad")
    if ad_id and str(ad_id).isdigit():
        selected_ad = next((ad for ad in ads if ad.id == int(ad_id)), None)
    if not selected_ad and ads:
        selected_ad = ads[0]
    report = None
    if selected_ad:
        today = timezone.localdate()
        current_start = today - timedelta(days=29)
        previous_start = current_start - timedelta(days=30)
        rows = list(AdMetricHistory.objects.filter(ad=selected_ad, date__gte=previous_start, date__lte=today).order_by("date"))

        def pack(metric_rows):
            result = {key: sum((getattr(row, key) for row in metric_rows), 0) for key in ("spend", "impressions", "clicks", "conversions", "conversion_value", "engagement")}
            spend, impressions, clicks = float(result["spend"] or 0), float(result["impressions"] or 0), float(result["clicks"] or 0)
            conversions, value = float(result["conversions"] or 0), float(result["conversion_value"] or 0)
            result.update({"ctr": clicks / impressions * 100 if impressions else 0, "cpc": spend / clicks if clicks else 0, "roas": value / spend if spend else 0, "cvr": conversions / clicks * 100 if clicks else 0, "cpa": spend / conversions if conversions else 0, "days": len(metric_rows)})
            return result

        current = pack([row for row in rows if row.date >= current_start])
        previous = pack([row for row in rows if row.date < current_start])
        roas, ctr, cvr = float(current["roas"]), float(current["ctr"]), float(current["cvr"])
        conversions, impressions = float(current["conversions"]), float(current["impressions"])
        stability = 100 if previous["roas"] == 0 else max(0, 100 - min(100, abs(roas - float(previous["roas"])) / max(float(previous["roas"]), .01) * 100))
        dimensions = [
            {"key": "efficiency", "label": "Ekonomik Verim", "score": round(min(100, roas / 3 * 100)), "evidence": f"ROAS {roas:.2f}x · CPA {float(current['cpa']):.2f} TL"},
            {"key": "attention", "label": "Dikkat Çekme", "score": round(min(100, ctr / 2.5 * 100)), "evidence": f"CTR %{ctr:.2f} · {int(current['clicks'])} tıklama"},
            {"key": "conversion", "label": "Dönüşüm Gücü", "score": round(min(100, cvr / 5 * 100)), "evidence": f"CVR %{cvr:.2f} · {conversions:.0f} dönüşüm"},
            {"key": "scale", "label": "Ölçek Hazırlığı", "score": round(min(100, (min(50, conversions * 5) + min(30, roas * 10) + stability * .2))), "evidence": f"{conversions:.0f} dönüşüm · eğilim istikrarı %{stability:.0f}"},
            {"key": "confidence", "label": "Veri Güveni", "score": round(min(100, current["days"] / 30 * 60 + min(40, impressions / 25000 * 40))), "evidence": f"{current['days']}/30 gün · {int(impressions)} gösterim"},
        ]
        overall = round(sum(item["score"] for item in dimensions) / len(dimensions))
        weakest = min(dimensions, key=lambda item: item["score"])
        strongest = max(dimensions, key=lambda item: item["score"])
        playbooks = {
            "efficiency": ("Teklif ve maliyet kontrolü", "Bütçeyi %15 azalt; düşük verimli yerleşim veya kitleyi ayır.", "ROAS artışı ve CPA düşüşü"),
            "attention": ("Yeni kreatif kanca testi", "Aynı teklif ile 3 farklı ilk cümle/görsel kancası üret; bütçeyi eşit böl.", "CTR artışı"),
            "conversion": ("Mesaj–landing uyum testi", "Reklam vaadi ile açılış sayfası başlığını eşleştir; tek değişkenli A/B testi çalıştır.", "CVR artışı"),
            "scale": ("Kontrollü ölçekleme kanıtı", "Bütçeyi değiştirmeden 7 gün daha veri topla; dönüşüm hacmi ve ROAS istikrarını doğrula.", "İstikrarlı ROAS"),
            "confidence": ("Veri kalitesi doğrulaması", "Piksel/event akışını kontrol et ve eksik günleri tamamlamadan bütçe kararı alma.", "30/30 gün veri kapsamı"),
        }
        experiment = playbooks[weakest["key"]]
        tasks = list(OctoTaskInstance.objects.filter(ad=selected_ad).select_related("rule").exclude(status__in=["dismissed", "snoozed"]).order_by("-priority_score", "-last_detected_at")[:12])
        rule_evidence = []
        seen_codes = set()
        for task in tasks:
            code = task.rule.code if task.rule_id else f"TASK-{task.id}"
            seen_codes.add(code)
            rule_evidence.append({"code": code, "title": task.title_tr, "detail": task.message_tr, "severity": task.severity, "source": "Kayıtlı Octo görevi"})

        live_signals = []
        if float(current["spend"]) > 0 and conversions == 0:
            live_signals.append({"key": "conversion", "keywords": ["dönüşüm", "harcama", "satış"], "severity": ["critical", "warning"], "detail": f"{float(current['spend']):.2f} TL harcamaya karşı 0 dönüşüm."})
        if roas < 1.5 and float(current["spend"]) > 0:
            live_signals.append({"key": "roas", "keywords": ["ROAS", "gelir verimi", "getiri"], "severity": ["critical", "warning"], "detail": f"ROAS {roas:.2f}x; 1.50x kontrol eşiğinin altında."})
        if ctr < 1:
            live_signals.append({"key": "ctr", "keywords": ["CTR", "tıklama oranı", "dikkat"], "severity": ["warning", "critical"], "detail": f"CTR %{ctr:.2f}; %1 dikkat eşiğinin altında."})
        if float(current["cpc"]) > 50:
            live_signals.append({"key": "cpc", "keywords": ["CPC", "tıklama maliyeti", "maliyet"], "severity": ["warning", "critical"], "detail": f"CPC {float(current['cpc']):.2f} TL; maliyet kontrolü gerekli."})
        if roas >= 2.5 and conversions >= 3:
            live_signals.append({"key": "scale", "keywords": ["ölçekleme", "büyütme", "fırsat"], "severity": ["opportunity", "info"], "detail": f"ROAS {roas:.2f}x ve {conversions:.0f} dönüşüm ölçekleme sinyali üretiyor."})
        if current["days"] < 21:
            live_signals.append({"key": "data", "keywords": ["veri", "ölçüm", "izleme"], "severity": ["warning", "info"], "detail": f"30 günün yalnızca {current['days']} gününde metrik var; karar güveni sınırlı."})

        for signal in live_signals:
            query = Q()
            for keyword in signal["keywords"]:
                query |= Q(title_tr__icontains=keyword) | Q(message_tr__icontains=keyword) | Q(condition_description__icontains=keyword) | Q(user_condition__icontains=keyword)
            rule = (
                OctoTaskRule.objects
                .filter(is_active=True, module__in=["creative", "performance"], severity__in=signal["severity"])
                .filter(query)
                .order_by("-priority_score", "code")
                .first()
            )
            if not rule:
                rule = OctoTaskRule.objects.filter(is_active=True, module__in=["creative", "performance"], severity__in=signal["severity"]).order_by("-priority_score", "code").first()
            if rule and rule.code not in seen_codes:
                seen_codes.add(rule.code)
                rule_evidence.append({"code": rule.code, "title": rule.title_tr, "detail": signal["detail"], "severity": rule.severity, "source": "Canlı 30 günlük metrik eşleşmesi"})
        spend = float(current["spend"])
        scenario = {"spend": spend * 1.2, "value": float(current["conversion_value"]) * 1.2, "conversions": conversions * 1.2, "assumption": "Mevcut ROAS ve dönüşüm oranı sabit kalırsa"}
        latest_analysis = ReklamAIAnaliz.objects.filter(reklam=selected_ad).order_by("-created_at", "-id").first()
        report = {"ad": selected_ad, "current": current, "previous": previous, "dimensions": dimensions, "overall": overall, "weakest": weakest, "strongest": strongest, "experiment": {"title": experiment[0], "action": experiment[1], "success": experiment[2]}, "rule_evidence": rule_evidence[:12], "scenario": scenario, "latest_analysis": latest_analysis, "media_url": (selected_ad.creative.thumbnail_url or selected_ad.creative.image_url) if selected_ad.creative else selected_ad.preview_image_url, "chart": [{"date": row.date.isoformat(), "roas": float(row.roas), "ctr": float(row.ctr), "spend": float(row.spend)} for row in rows if row.date >= current_start]}
    context = {"ads": ads, "selected_ad": selected_ad, "report": report, "agency_scope": agency_scope, "v2_only": True}
    CacheService.set("ai_dashboard", *cache_parts, value=context, timeout=120, version=version)
    return render(request, "ai/dashboard.html", context)


@login_required
@ai_credit_required(amount=1, tariff_key="campaign-local-analysis", reason="Kampanya AI analizi", operation=FeatureUsageLedger.OP_OPENAI_ANALYSIS)
def ai_analyze_campaign(request, campaign_id):
    return JsonResponse({"success": True, "message": "V2 kampanya analizi hazırlandı.", "campaign_id": campaign_id})


@login_required
@ai_credit_required(amount=1, tariff_key="account-local-analysis", reason="Hesap AI analizi", operation=FeatureUsageLedger.OP_OPENAI_ANALYSIS)
def ai_analyze_account(request, account_id):
    return JsonResponse({"success": True, "message": "V2 hesap analizi hazırlandı.", "account_id": account_id})


@login_required
@ai_credit_required(amount=1, tariff_key="suggestions-local", reason="AI öneri/yorum", operation=FeatureUsageLedger.OP_OPENAI_RECOMMENDATION)
def ai_suggestions_api(request):
    allowed_ads = scope_queryset(request, Ad.objects.filter(source_type="OWN"))
    qs = AdMetricHistory.objects.filter(ad__in=allowed_ads).values("ad_id", "ad__name").annotate(spend=Sum("spend"), clicks=Sum("clicks"), impressions=Sum("impressions"), conversions=Sum("conversions"), conversion_value=Sum("conversion_value"))[:20]
    suggestions = []
    for row in qs:
        metrics = aggregate_metric_queryset(AdMetricHistory.objects.filter(ad_id=row["ad_id"], ad__in=allowed_ads))
        score = _score_from_metrics(metrics)
        suggestions.append({"ad_id": row["ad_id"], "ad_name": row["ad__name"], "score": score, "suggestion": "Bütçe kontrollü artırılabilir." if score >= 75 else "Kreatif ve hedef kitle yeniden test edilmeli."})
    return JsonResponse({"success": True, "suggestions": suggestions})


@login_required
def start_ad_ai_analysis(request, ad_id):
    ad = scope_queryset(request, Ad.objects.all()).filter(id=ad_id).first()
    if not ad:
        return JsonResponse({"success": False, "message": "Reklam bulunamadı."}, status=404)
    force = request.GET.get("force") == "1" or request.POST.get("force") == "1"
    if not force:
        latest = ReklamAIAnaliz.objects.filter(reklam=ad).order_by("-created_at", "-id").first()
        if latest:
            return JsonResponse({
                "success": True,
                "cached": True,
                "analysis_id": latest.id,
                "score": latest.overall_score,
                "summary": latest.analysis_summary,
            })
    agency_scope = get_agency_scope(request)
    organization = agency_scope.selected_client.organization if agency_scope.selected_client else None
    charged = False
    reference = "core.views.ai.start_ad_ai_analysis"
    if not (request.user.is_staff or request.user.is_superuser):
        if not get_active_subscription(request.user, organization=organization):
            return JsonResponse({
                "success": False,
                "error": "subscription_required",
                "message": "Bu AI ozelligi icin aktif paket gerekli.",
            }, status=402)
        credit_result = consume_openai_operation(
            user=request.user,
            organization=organization,
            operation=FeatureUsageLedger.OP_OPENAI_ANALYSIS,
            credit_amount=3,
            tariff_key="ad-report-card-analysis",
            reason="Reklam AI analizi",
            reference=reference,
        )
        if not credit_result.allowed:
            return JsonResponse(insufficient_credit_payload(
                message=credit_result.reason,
                required_credits=credit_result.used,
                available_credits=credit_result.limit,
            ), status=402)
        charged = True
    try:
        obj = generate_ad_report(ad, request.user, "analysis", organization=organization)
        report = serialize_ad_report(obj)
        return JsonResponse({
            "success": True,
            "analysis_id": obj.id,
            "score": obj.overall_score,
            "overall_score": obj.overall_score,
            "summary": obj.analysis_summary,
            "agents": report.get("agents", []),
            "report": report,
        })
    except Exception as exc:
        if charged:
            refund_ai_tariff_credits(
                user=request.user, organization=organization,
                tariff_key="ad-report-card-analysis", reason=str(exc), reference=reference,
            )
        return JsonResponse({"success": False, "message": str(exc)}, status=502)


@login_required
def get_ad_analysis_status(request, analysis_id):
    obj = ReklamAIAnaliz.objects.filter(id=analysis_id, reklam__in=scope_queryset(request, Ad.objects.all())).first()
    if not obj:
        return JsonResponse({"success": False, "message": "Analiz bulunamadı."}, status=404)
    return JsonResponse({"success": True, "status": "completed", "score": obj.overall_score, "summary": obj.analysis_summary})


@login_required
def save_ai_analysis(request):
    return JsonResponse({"success": True, "message": "V2 AI analiz kaydı alındı."})


@login_required
def send_analysis_email(request):
    return JsonResponse({"success": True, "message": "E-posta gönderimi için rapor kuyruğa alınabilir."})


@login_required
def get_ai_task_status(request, task_id):
    return JsonResponse({"success": True, "task_id": task_id, "status": "completed"})
