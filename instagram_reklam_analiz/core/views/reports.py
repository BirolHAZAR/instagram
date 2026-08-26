from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from smtplib import SMTPAuthenticationError
from datetime import timedelta

from core.forms import ScheduledReportForm
from core.models import Ad, AdMetricHistory, ActivityLog, AgencyClient, BudgetOptimizationLog, BudgetOptimizationRule, Campaign, OctoTaskInstance, Report, ScheduledReport
from core.services.scheduled_reports import (
    build_report_context,
    build_scheduled_report_pdf,
    ensure_next_run,
    scheduled_report_filename,
    send_scheduled_report as send_report_now,
)
from core.services.agency_scope import get_agency_scope, scope_queryset
from core.services.cache_service import CacheService


def _scheduled_report_form(request, *args, **kwargs):
    scope = get_agency_scope(request)
    campaigns = scope_queryset(request, Campaign.objects.all())
    instance = kwargs.get("instance")
    selected_client_id = request.POST.get("agency_client") if request.method == "POST" else None
    if not selected_client_id and instance and instance.pk:
        selected_client_id = instance.agency_client_id
    if not selected_client_id and scope.selected_client:
        selected_client_id = scope.selected_client.id
    allowed_client_ids = {client.id for client in scope.clients}
    if scope.is_agency:
        campaigns = (
            campaigns.filter(platform_account__agency_client_id=selected_client_id)
            if str(selected_client_id).isdigit() and int(selected_client_id) in allowed_client_ids
            else campaigns.none()
        )
    return ScheduledReportForm(
        *args,
        user=request.user,
        campaigns_queryset=campaigns,
        agency_clients=(AgencyClient.objects.filter(id__in=[client.id for client in scope.clients]) if scope.is_agency else None),
        initial={**kwargs.pop("initial", {}), **({"agency_client": selected_client_id} if selected_client_id else {})},
        **kwargs,
    )


@login_required
def report_client_campaigns(request):
    scope = get_agency_scope(request)
    raw_client_id = (request.GET.get("agency_client") or "").strip()
    client = next((item for item in scope.clients if str(item.id) == raw_client_id), None)
    if not scope.is_agency or client is None:
        return JsonResponse({"campaigns": []})
    campaigns = Campaign.objects.filter(
        platform_account__agency_client=client
    ).order_by("name").values("id", "name")
    return JsonResponse({"campaigns": list(campaigns)})


@login_required
def report_client_ads(request):
    scope = get_agency_scope(request)
    raw_client_id = (request.GET.get("agency_client") or "").strip()
    client = next((item for item in scope.clients if str(item.id) == raw_client_id), None)
    if not scope.is_agency or client is None:
        return JsonResponse({"ads": []})
    ads = (
        Ad.objects.filter(source_type="OWN", platform_account__agency_client=client)
        .select_related("platform_account__platform")
        .order_by("-created_at")[:300]
    )
    return JsonResponse({"ads": [
        {"id": ad.id, "name": ad.name or ad.platform_ad_id, "platform": ad.platform_account.platform.name}
        for ad in ads
    ]})


@login_required
def report_list(request):
    return render(
        request,
        "reports/list.html",
        {
            "reports": Report.objects.filter(user=request.user),
            "scheduled_reports": ScheduledReport.objects.filter(user=request.user).prefetch_related("campaigns"),
            "v2_only": True,
        },
    )


@login_required
def generate_report(request):
    if request.method == "POST":
        form = _scheduled_report_form(request, request.POST)
        if form.is_valid():
            scheduled_report = form.save(commit=False)
            scheduled_report.user = request.user
            scheduled_report.save()
            form.save_m2m()
            if scheduled_report.agency_client_id and not scheduled_report.campaigns.exists():
                scheduled_report.campaigns.set(
                    Campaign.objects.filter(platform_account__agency_client=scheduled_report.agency_client)
                )
            ensure_next_run(scheduled_report)
            messages.success(request, "Otomatik rapor ayarı oluşturuldu.")
            return redirect("scheduled_report_preview", report_id=scheduled_report.id)
    else:
        form = _scheduled_report_form(request, initial={"recipient_emails_input": request.user.email, "send_hour": 9})
    return render(request, "reports/generate.html", {"form": form, "v2_only": True})


@login_required
def report_detail(request, report_id):
    report = Report.objects.filter(id=report_id, user=request.user).first()
    return render(request, "reports/generate.html", {"report": report, "v2_only": True})


@login_required
def report_delete(request, report_id):
    Report.objects.filter(id=report_id, user=request.user).delete()
    return redirect("report_list")


@login_required
def scheduled_report_edit(request, report_id):
    scheduled_report = get_object_or_404(ScheduledReport, id=report_id, user=request.user)
    if request.method == "POST":
        form = _scheduled_report_form(request, request.POST, instance=scheduled_report)
        if form.is_valid():
            scheduled_report = form.save()
            ensure_next_run(scheduled_report)
            messages.success(request, "Otomatik rapor ayarı güncellendi.")
            return redirect("scheduled_report_preview", report_id=scheduled_report.id)
    else:
        form = _scheduled_report_form(request, instance=scheduled_report)
    return render(request, "reports/generate.html", {"form": form, "scheduled_report": scheduled_report, "v2_only": True})


@login_required
def scheduled_report_delete(request, report_id):
    scheduled_report = get_object_or_404(ScheduledReport, id=report_id, user=request.user)
    if request.method == "POST":
        scheduled_report.delete()
        messages.success(request, "Otomatik rapor ayarı silindi.")
    return redirect("report_list")


@login_required
def scheduled_report_toggle(request, report_id):
    scheduled_report = get_object_or_404(ScheduledReport, id=report_id, user=request.user)
    if request.method == "POST":
        scheduled_report.is_active = not scheduled_report.is_active
        if scheduled_report.is_active:
            scheduled_report.next_run_at = timezone.now()
        scheduled_report.save(update_fields=["is_active", "next_run_at", "updated_at"])
        ensure_next_run(scheduled_report)
        messages.success(request, "Rapor durumu güncellendi.")
    return redirect("report_list")


@login_required
def scheduled_report_send_now(request, report_id):
    if request.method == "POST":
        try:
            with transaction.atomic():
                scheduled_report = get_object_or_404(
                    ScheduledReport.objects.select_for_update(),
                    id=report_id,
                    user=request.user,
                )
                recently_sent_after = timezone.now() - timedelta(seconds=60)
                if scheduled_report.last_sent_at and scheduled_report.last_sent_at >= recently_sent_after:
                    messages.info(request, "Bu rapor az önce gönderildi; yinelenen gönderim engellendi.")
                    return redirect("report_list")
                send_report_now(scheduled_report)
            messages.success(request, "Rapor alıcılara gönderildi.")
        except SMTPAuthenticationError:
            messages.error(
                request,
                "Rapor gönderilemedi: SMTP kullanıcı/şifre reddedildi. "
                "Web ve Celery servislerini yeniden başlatın; EMAIL_HOST_USER info@reklamanaliz.net olmalı.",
            )
        except Exception as exc:
            messages.error(request, f"Rapor gönderilemedi: {exc}")
    return redirect("report_list")


@login_required
def scheduled_report_preview(request, report_id):
    scheduled_report = get_object_or_404(ScheduledReport, id=report_id, user=request.user)
    preview_context = build_report_context(scheduled_report)
    return render(
        request,
        "reports/preview.html",
        {
            "scheduled_report": scheduled_report,
            "preview_context": preview_context,
            "v2_only": True,
        },
    )


@login_required
@xframe_options_sameorigin
def scheduled_report_preview_html(request, report_id):
    scheduled_report = get_object_or_404(ScheduledReport, id=report_id, user=request.user)
    preview_context = build_report_context(scheduled_report)
    preview_html = render_to_string("emails/scheduled_report.html", preview_context)
    return HttpResponse(preview_html, content_type="text/html; charset=utf-8")


@login_required
def scheduled_report_pdf(request, report_id):
    scheduled_report = get_object_or_404(ScheduledReport, id=report_id, user=request.user)
    pdf = build_scheduled_report_pdf(scheduled_report)
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{scheduled_report_filename(scheduled_report)}"'
    return response


@login_required
def reklam_karsilastirma(request):
    scope = get_agency_scope(request)
    all_ads = list(
        scope_queryset(request, Ad.objects.filter(source_type="OWN"))
        .select_related("platform_account__platform", "platform_account__agency_client", "campaign", "creative")
        .order_by("-created_at")[:300]
    )
    allowed_clients = {str(client.id): client for client in scope.clients}
    client_a_id = (request.GET.get("client_a") or "").strip()
    client_b_id = (request.GET.get("client_b") or "").strip()
    client_a = allowed_clients.get(client_a_id) if scope.is_agency else None
    client_b = allowed_clients.get(client_b_id) if scope.is_agency else None
    ads_a = [ad for ad in all_ads if not scope.is_agency or (client_a and ad.platform_account.agency_client_id == client_a.id)]
    ads_b = [ad for ad in all_ads if not scope.is_agency or (client_b and ad.platform_account.agency_client_id == client_b.id)]
    try:
        days = int(request.GET.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    days = days if days in {7, 30, 90} else 30
    selected = []
    for key, available_ads in (("ad_a", ads_a), ("ad_b", ads_b)):
        value = request.GET.get(key)
        if value and str(value).isdigit():
            ad = next((row for row in available_ads if row.id == int(value)), None)
            if ad and ad not in selected:
                selected.append(ad)

    start_date = timezone.localdate() - timedelta(days=days - 1)

    def build_ad_report(ad):
        rows = list(AdMetricHistory.objects.filter(ad=ad, date__gte=start_date).order_by("date"))
        totals = {
            "impressions": sum(row.impressions for row in rows),
            "reach": sum(row.reach for row in rows),
            "clicks": sum(row.clicks for row in rows),
            "spend": sum((row.spend for row in rows), 0),
            "conversions": sum((row.conversions for row in rows), 0),
            "conversion_value": sum((row.conversion_value for row in rows), 0),
            "engagement": sum(row.engagement for row in rows),
        }
        impressions = float(totals["impressions"] or 0)
        clicks = float(totals["clicks"] or 0)
        spend = float(totals["spend"] or 0)
        conversions = float(totals["conversions"] or 0)
        value = float(totals["conversion_value"] or 0)
        totals.update({
            "ctr": clicks / impressions * 100 if impressions else 0,
            "cpc": spend / clicks if clicks else 0,
            "cpm": spend / impressions * 1000 if impressions else 0,
            "roas": value / spend if spend else 0,
            "conversion_rate": conversions / clicks * 100 if clicks else 0,
            "cost_per_conversion": spend / conversions if conversions else 0,
            "engagement_rate": float(totals["engagement"] or 0) / impressions * 100 if impressions else 0,
        })
        platform = getattr(getattr(ad.platform_account, "platform", None), "name", "")
        media_url = ""
        if ad.creative:
            media_url = ad.creative.thumbnail_url or ad.creative.image_url or ""
        return {
            "ad": ad,
            "platform": platform,
            "media_url": media_url,
            "totals": totals,
            "row_count": len(rows),
            "chart": [{"date": row.date.isoformat(), "spend": float(row.spend), "clicks": row.clicks, "conversions": float(row.conversions), "roas": float(row.roas)} for row in rows],
        }

    reports = [build_ad_report(ad) for ad in selected]
    comparisons = []
    if len(reports) == 2:
        definitions = [
            ("ROAS", "roas", True, "x"), ("CTR", "ctr", True, "%"),
            ("Dönüşüm", "conversions", True, ""), ("Dönüşüm Oranı", "conversion_rate", True, "%"),
            ("CPC", "cpc", False, " TL"), ("Dönüşüm Maliyeti", "cost_per_conversion", False, " TL"),
            ("Gösterim", "impressions", True, ""), ("Harcama", "spend", None, " TL"),
        ]
        for label, key, higher_is_better, suffix in definitions:
            a, b = float(reports[0]["totals"][key] or 0), float(reports[1]["totals"][key] or 0)
            winner = "tie" if a == b or higher_is_better is None else "a" if (a > b) == higher_is_better else "b"
            comparisons.append({"label": label, "key": key, "a": a, "b": b, "difference": abs(a - b), "winner": winner, "suffix": suffix})
        wins_a = sum(row["winner"] == "a" for row in comparisons)
        wins_b = sum(row["winner"] == "b" for row in comparisons)
        overall_winner = "tie" if wins_a == wins_b else "a" if wins_a > wins_b else "b"
    else:
        wins_a = wins_b = 0
        overall_winner = "tie"

    return render(request, "reports/reklam_karsilastirma.html", {
        "ads_a": ads_a, "ads_b": ads_b, "agency_scope": scope,
        "client_a": client_a, "client_b": client_b,
        "comparison_ads_json": [
            {"id": ad.id, "name": ad.name or ad.platform_ad_id, "platform": ad.platform_account.platform.name,
             "client_id": ad.platform_account.agency_client_id}
            for ad in all_ads if ad.platform_account.agency_client_id
        ],
        "reports": reports, "comparisons": comparisons, "days": days,
        "wins_a": wins_a, "wins_b": wins_b, "overall_winner": overall_winner, "v2_only": True,
    })


@login_required
def rakip_reklam_karsilastirma(request):
    competitor = scope_queryset(request, Ad.objects.filter(source_type="COMPETITOR"))
    return render(request, "reports/reklam_tarihcesi.html", {"reklamlar": competitor, "v2_only": True})


@login_required
def reklam_tarihcesi(request):
    agency_scope = get_agency_scope(request)
    ads = list(
        scope_queryset(request, Ad.objects.filter(source_type="OWN"))
        .select_related("platform_account__platform", "campaign", "ad_group", "creative")
        .order_by("-last_synced_at", "-created_at")[:300]
    )
    selected_ad = None
    ad_id = request.GET.get("ad")
    if ad_id and str(ad_id).isdigit():
        selected_ad = next((ad for ad in ads if ad.id == int(ad_id)), None)
    if not selected_ad and ads:
        selected_ad = ads[0]
    try:
        days = int(request.GET.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    days = days if days in {7, 30, 90} else 30
    report = None
    if selected_ad:
        end_date = timezone.localdate()
        start_date = end_date - timedelta(days=days - 1)
        previous_start = start_date - timedelta(days=days)
        rows = list(AdMetricHistory.objects.filter(ad=selected_ad, date__gte=previous_start, date__lte=end_date).order_by("date"))
        current_rows = [row for row in rows if row.date >= start_date]
        previous_rows = [row for row in rows if row.date < start_date]

        def totals(metric_rows):
            result = {key: sum((getattr(row, key) for row in metric_rows), 0) for key in ("impressions", "reach", "clicks", "spend", "conversions", "conversion_value", "engagement")}
            impressions, clicks, spend = float(result["impressions"] or 0), float(result["clicks"] or 0), float(result["spend"] or 0)
            conversions, value = float(result["conversions"] or 0), float(result["conversion_value"] or 0)
            result.update({"ctr": clicks / impressions * 100 if impressions else 0, "cpc": spend / clicks if clicks else 0, "cpm": spend / impressions * 1000 if impressions else 0, "roas": value / spend if spend else 0, "conversion_rate": conversions / clicks * 100 if clicks else 0, "cost_per_conversion": spend / conversions if conversions else 0})
            return result

        current, previous = totals(current_rows), totals(previous_rows)
        metrics = []
        for label, key, suffix, lower_better in (("Harcama", "spend", " TL", False), ("Gösterim", "impressions", "", False), ("Tıklama", "clicks", "", False), ("CTR", "ctr", "%", False), ("CPC", "cpc", " TL", True), ("ROAS", "roas", "x", False), ("Dönüşüm", "conversions", "", False), ("Dönüşüm Maliyeti", "cost_per_conversion", " TL", True)):
            now, before = float(current[key] or 0), float(previous[key] or 0)
            delta = ((now - before) / abs(before) * 100) if before else (100 if now else 0)
            positive = delta < 0 if lower_better else delta > 0
            metrics.append({"label": label, "key": key, "value": now, "previous": before, "delta": delta, "positive": positive, "suffix": suffix})

        signals = []
        for metric in metrics:
            if abs(metric["delta"]) >= 20 and metric["key"] not in {"impressions", "spend"}:
                signals.append({"level": "good" if metric["positive"] else "bad", "title": f"{metric['label']} {'yükseldi' if metric['delta'] > 0 else 'düştü'}", "detail": f"Önceki {days} güne göre %{abs(metric['delta']):.1f} değişim."})
        if not current_rows:
            signals.append({"level": "bad", "title": "Metrik verisi bulunamadı", "detail": "Seçilen dönemde bu reklam için günlük performans kaydı yok."})

        tasks = list(OctoTaskInstance.objects.filter(user=request.user, ad=selected_ad).select_related("rule").order_by("-last_detected_at")[:30])
        budgets = list(BudgetOptimizationLog.objects.filter(user=request.user, reklam=selected_ad).order_by("-created_at")[:30])
        activities = list(ActivityLog.objects.filter(user=request.user, action_type__in=["ad", "optimization", "ai"]).filter(metadata__ad_id=selected_ad.id).order_by("-created_at")[:30])
        timeline = []
        if selected_ad.started_at or selected_ad.first_seen_at:
            timeline.append({"date": selected_ad.started_at or selected_ad.first_seen_at, "type": "status", "title": "Reklam yayına alındı", "detail": selected_ad.get_status_display()})
        if selected_ad.creative:
            timeline.append({"date": selected_ad.creative.updated_at, "type": "creative", "title": "Bağlı kreatif", "detail": str(selected_ad.creative)})
        for log in budgets:
            timeline.append({"date": log.created_at, "type": "budget", "title": "Bütçe değişikliği", "detail": f"{log.old_budget} TL → {log.new_budget} TL · {log.reason}"})
        for task in tasks:
            timeline.append({"date": task.last_detected_at, "type": "rule", "title": task.title_tr, "detail": task.message_tr, "severity": task.severity, "code": task.rule.code if task.rule_id else ""})
        for activity in activities:
            timeline.append({"date": activity.created_at, "type": "activity", "title": activity.title, "detail": activity.message})
        if selected_ad.ended_at:
            timeline.append({"date": selected_ad.ended_at, "type": "status", "title": "Reklam sona erdi", "detail": selected_ad.get_status_display()})
        timeline.sort(key=lambda event: event["date"] or timezone.now(), reverse=True)
        creative = selected_ad.creative
        report = {"ad": selected_ad, "current": current, "metrics": metrics, "rows": list(reversed(current_rows)), "chart": [{"date": row.date.isoformat(), "spend": float(row.spend), "roas": float(row.roas)} for row in current_rows], "signals": signals[:8], "tasks": tasks, "budgets": budgets, "timeline": timeline[:60], "start_date": start_date, "end_date": end_date, "coverage": len(current_rows), "creative": creative, "media_url": (creative.thumbnail_url or creative.image_url or selected_ad.preview_image_url) if creative else selected_ad.preview_image_url}
    return render(request, "reports/reklam_tarihcesi_v2.html", {
        "ads": ads, "selected_ad": selected_ad, "report": report, "days": days,
        "agency_scope": agency_scope, "v2_only": True,
    })


@login_required
def daily_budget_report(request):
    agency_scope = get_agency_scope(request)
    today = timezone.localdate()
    version = CacheService.get_version("daily_budget_report", request.user.id)
    cache_parts = ("user", request.user.id, "scope", agency_scope.cache_key, "day", today.isoformat())
    cached = CacheService.get("daily_budget_report", *cache_parts, version=version)
    if cached is not None:
        cached = dict(cached)
        cached["agency_scope"] = agency_scope
        return render(request, "reports/daily_budget_report.html", cached)
    start_date = today - timedelta(days=29)
    current_start = today - timedelta(days=6)
    previous_start = current_start - timedelta(days=7)
    base_metrics = scope_queryset(
        request,
        AdMetricHistory.objects.filter(ad__source_type="OWN"),
        account_lookup="ad__platform_account",
        user_lookup="ad__user",
    )
    daily_rows = list(base_metrics.filter(date__gte=start_date).values("date").annotate(spend=Sum("spend"), conversion_value=Sum("conversion_value"), conversions=Sum("conversions"), clicks=Sum("clicks"), impressions=Sum("impressions")).order_by("date"))
    for row in daily_rows:
        spend, value = float(row["spend"] or 0), float(row["conversion_value"] or 0)
        row["roas"] = value / spend if spend else 0

    def aggregate_period(start, end):
        return {row["ad_id"]: row for row in base_metrics.filter(date__gte=start, date__lte=end).values("ad_id").annotate(spend=Sum("spend"), conversion_value=Sum("conversion_value"), conversions=Sum("conversions"), clicks=Sum("clicks"), impressions=Sum("impressions"))}

    current_map = aggregate_period(current_start, today)
    previous_map = aggregate_period(previous_start, current_start - timedelta(days=1))
    ads = list(scope_queryset(request, Ad.objects.filter(source_type="OWN", id__in=current_map.keys())).select_related("platform_account__platform", "campaign").order_by("name"))
    rules = {}
    for rule in BudgetOptimizationRule.objects.filter(user=request.user, is_active=True).order_by("-updated_at"):
        rules.setdefault(rule.platform_id, rule)
    recommendations = []
    totals = {"spend": 0.0, "value": 0.0, "conversions": 0.0, "increases": 0, "decreases": 0, "maintains": 0, "risks": 0}
    for ad in ads:
        now, before = current_map.get(ad.id, {}), previous_map.get(ad.id, {})
        spend, value = float(now.get("spend") or 0), float(now.get("conversion_value") or 0)
        conversions, clicks = float(now.get("conversions") or 0), float(now.get("clicks") or 0)
        impressions = float(now.get("impressions") or 0)
        previous_spend, previous_value = float(before.get("spend") or 0), float(before.get("conversion_value") or 0)
        roas, previous_roas = (value / spend if spend else 0), (previous_value / previous_spend if previous_spend else 0)
        cpc = spend / clicks if clicks else 0
        platform = getattr(ad.platform_account, "platform", None) if ad.platform_account_id else None
        rule = rules.get(getattr(platform, "id", None))
        target_roas = float(rule.roas_target) if rule else 2.0
        latest_budget_log = BudgetOptimizationLog.objects.filter(user=request.user, reklam=ad, success=True, is_reverted=False).order_by("-created_at").first()
        current_budget = float(latest_budget_log.new_budget) if latest_budget_log else float((ad.raw_data or {}).get("daily_budget") or spend / 7 if spend else 0)
        action, percent, confidence = "maintain", 0, 68
        reasons = []
        if spend > 0 and conversions == 0:
            action, percent, confidence = "risk", -30, 92
            reasons = ["Son 7 günde harcama var ancak dönüşüm yok.", "Bütçe azaltılmalı veya reklam durdurulmadan önce izleme doğrulanmalı."]
        elif roas >= target_roas * 1.25 and conversions >= 2 and (previous_roas == 0 or roas >= previous_roas * .85):
            action, percent, confidence = "increase", 20, 88
            reasons = [f"ROAS {roas:.2f}x ile {target_roas:.2f}x hedefinin üzerinde.", "Dönüşüm hacmi ölçekleme için yeterli ve eğilim korunuyor."]
        elif spend > 0 and roas < target_roas * .65:
            action, percent, confidence = "decrease", -20, 86
            reasons = [f"ROAS {roas:.2f}x ile {target_roas:.2f}x hedefinin belirgin altında.", "Verimsiz harcamayı sınırlamak için kontrollü azaltım öneriliyor."]
        else:
            reasons = [f"ROAS {roas:.2f}x ve dönüşüm hacmi mevcut bütçeyi koruma aralığında.", "Yeni veri gelene kadar agresif değişiklik önerilmiyor."]
        proposed_budget = current_budget * (1 + percent / 100) if current_budget else 0
        if rule and proposed_budget:
            proposed_budget = max(float(rule.min_budget), min(float(rule.max_budget), proposed_budget))
        totals["spend"] += spend; totals["value"] += value; totals["conversions"] += conversions
        totals[{"increase": "increases", "decrease": "decreases", "maintain": "maintains", "risk": "risks"}[action]] += 1
        recommendations.append({"ad": ad, "platform": getattr(platform, "name", "—"), "spend": spend, "roas": roas, "previous_roas": previous_roas, "conversions": conversions, "cpc": cpc, "action": action, "percent": percent, "confidence": confidence, "reasons": reasons, "current_budget": current_budget, "proposed_budget": proposed_budget, "target_roas": target_roas})
    action_order = {"risk": 0, "decrease": 1, "increase": 2, "maintain": 3}
    recommendations.sort(key=lambda row: (action_order[row["action"]], -row["confidence"], -row["spend"]))
    totals["roas"] = totals["value"] / totals["spend"] if totals["spend"] else 0
    budget_logs = []
    scoped_own_ads = scope_queryset(request, Ad.objects.filter(source_type="OWN"))
    budget_log_qs = BudgetOptimizationLog.objects.filter(
        user=request.user,
        reklam__in=scoped_own_ads,
        created_at__date__gte=start_date,
    ).select_related("reklam", "rule").order_by("-created_at")[:50]
    for log in budget_log_qs:
        old_budget, new_budget = float(log.old_budget or 0), float(log.new_budget or 0)
        budget_logs.append({"log": log, "change_percent": ((new_budget - old_budget) / old_budget * 100) if old_budget else 0})
    chart = [{"date": row["date"].isoformat(), "spend": float(row["spend"] or 0), "roas": row["roas"], "conversions": float(row["conversions"] or 0)} for row in daily_rows]
    context = {
        "rows": daily_rows, "chart": chart, "totals": totals,
        "recommendations": recommendations, "budget_logs": budget_logs,
        "start_date": start_date, "end_date": today,
        "agency_scope": agency_scope, "v2_only": True,
    }
    CacheService.set("daily_budget_report", *cache_parts, value=context, timeout=120, version=version)
    return render(request, "reports/daily_budget_report.html", context)


@login_required
def api_reklam_listesi(request):
    qs = scope_queryset(request, Ad.objects.filter(source_type="OWN")).order_by("-created_at")[:300]
    return JsonResponse({"success": True, "reklamlar": [{"id": a.id, "name": str(a), "status": a.status} for a in qs]})


@login_required
def api_reklam_detay(request, reklam_id):
    ad = scope_queryset(request, Ad.objects.filter(id=reklam_id, source_type="OWN")).first()
    if not ad:
        return JsonResponse({"success": False}, status=404)
    metrics = AdMetricHistory.objects.filter(ad=ad).order_by("date")
    return JsonResponse({"success": True, "ad": {"id": ad.id, "name": str(ad)}, "metrics": [{"date": m.date.isoformat(), "spend": float(m.spend), "clicks": m.clicks, "impressions": m.impressions} for m in metrics]})


@login_required
def api_rakip_reklam_listesi(request):
    qs = scope_queryset(request, Ad.objects.filter(source_type="COMPETITOR")).order_by("-created_at")[:300]
    return JsonResponse({"success": True, "reklamlar": [{"id": a.id, "name": str(a), "status": a.status} for a in qs]})


@login_required
def api_rakip_reklam_detay(request, reklam_id):
    ad = scope_queryset(request, Ad.objects.filter(id=reklam_id, source_type="COMPETITOR")).first()
    if not ad:
        return JsonResponse({"success": False}, status=404)
    return JsonResponse({"success": True, "ad": {"id": ad.id, "name": str(ad), "text": ad.primary_text}})
