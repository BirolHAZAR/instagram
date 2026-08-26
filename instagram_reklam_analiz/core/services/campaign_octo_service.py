from decimal import Decimal, InvalidOperation

from django.db import transaction

from core.models import CampaignMetricHistory, CampaignOctoAnalysis, CampaignOctoRecommendation
from core.services.performance_metrics import aggregate_metric_queryset


def d(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def safe_div(numerator, denominator):
    numerator = d(numerator)
    denominator = d(denominator)
    if denominator == 0:
        return Decimal("0")
    return numerator / denominator


def score_roas(roas):
    roas = d(roas)
    if roas >= 5:
        return Decimal("100")
    if roas >= 3:
        return Decimal("80")
    if roas >= Decimal("1.5"):
        return Decimal("60")
    if roas > 0:
        return Decimal("35")
    return Decimal("10")


def score_ctr(ctr):
    ctr = d(ctr)
    if ctr >= 4:
        return Decimal("100")
    if ctr >= 2:
        return Decimal("75")
    if ctr >= 1:
        return Decimal("55")
    if ctr > 0:
        return Decimal("30")
    return Decimal("10")


def score_cpc(cpc):
    cpc = d(cpc)
    if Decimal("0") < cpc <= 2:
        return Decimal("100")
    if cpc <= 5:
        return Decimal("75")
    if cpc <= 10:
        return Decimal("50")
    if cpc > 0:
        return Decimal("25")
    return Decimal("10")


def status_from_score(score, roas):
    score = d(score)
    roas = d(roas)

    if score >= 85 and roas >= 3:
        return "excellent", "low"
    if score >= 70 and roas >= 2:
        return "good", "low"
    if score >= 50:
        return "watch", "medium"
    if score >= 30:
        return "risky", "high"
    return "critical", "critical"


def build_texts(campaign, metrics, status, risk_level):
    name = getattr(campaign, "name", None) or getattr(campaign, "campaign_name", None) or str(campaign)

    roas = d(metrics["roas"])
    ctr = d(metrics["ctr"])
    cpc = d(metrics["cpc"])
    spend = d(metrics["spend"])
    budget = d(metrics["budget"])
    conversions = d(metrics["conversions"])

    analysis_text = "\n".join([
        f"- {name} kampanyası son metriklere göre {status} durumunda görünüyor.",
        f"- ROAS: {roas:.2f}x, CTR: %{ctr:.2f}, CPC: {cpc:.2f} TL.",
        f"- Toplam harcama: {spend:.2f} TL, toplam bütçe: {budget:.2f} TL, dönüşüm: {conversions:.2f}.",
        f"- Risk seviyesi: {risk_level}.",
    ])

    strengths = []
    weaknesses = []
    recommendations = []

    if roas >= 3:
        strengths.append("ROAS güçlü; harcanan bütçe satış/değer üretimi açısından verimli.")
        recommendations.append("Performans korunuyorsa bütçe kontrollü şekilde artırılabilir.")
    elif roas > 0:
        weaknesses.append("ROAS düşük; kampanya harcamaya göre yeterli değer üretmiyor.")
        recommendations.append("Hedef kitle, teklif stratejisi ve kreatif performansı yeniden incelenmeli.")
    else:
        weaknesses.append("ROAS oluşmamış; dönüşüm değeri veya satış verisi eksik olabilir.")
        recommendations.append("Pixel/Conversion API, dönüşüm olayı ve gelir aktarımı kontrol edilmeli.")

    if ctr >= 2:
        strengths.append("CTR iyi; kreatif ve mesaj kullanıcı ilgisi oluşturuyor.")
    else:
        weaknesses.append("CTR düşük; reklam metni/görseli kullanıcıyı yeterince tıklamaya yönlendirmiyor.")
        recommendations.append("Yeni kreatif varyasyonları ve daha net teklif mesajı test edilmeli.")

    if cpc > 8:
        weaknesses.append("CPC yüksek; tıklama maliyeti bütçe verimliliğini düşürüyor.")
        recommendations.append("Kitle daraltma/genişletme testi ve teklif optimizasyonu yapılmalı.")
    elif cpc > 0:
        strengths.append("CPC kabul edilebilir seviyede; trafik maliyeti kontrol altında.")

    if not strengths:
        strengths.append("Kampanya izlenebilir veri üretmeye başlamış; sonraki kararlar için temel oluşuyor.")
    if not weaknesses:
        weaknesses.append("Belirgin kritik zayıflık görünmüyor; frekans ve kreatif yorgunluğu izlenmeli.")
    if not recommendations:
        recommendations.append("Mevcut performans korunmalı; bütçe artışı küçük oranlarla test edilmeli.")

    return {
        "analysis_text": analysis_text,
        "summary": f"{name} kampanyası {status} durumunda. Risk seviyesi: {risk_level}.",
        "strengths": "\n".join(f"- {x}" for x in strengths),
        "weaknesses": "\n".join(f"- {x}" for x in weaknesses),
        "recommendations": "\n".join(f"- {x}" for x in recommendations),
        "expected_impact": "Öneriler uygulandıktan sonra sonuçlar 3-7 günlük yeni metriklerle tekrar ölçülmelidir.",
    }


@transaction.atomic
def create_campaign_octo_records(campaign, user=None, source="real"):
    """
    CampaignMetricHistory roas alanını tutar; yine de kampanya geneli için
    oranlar satır ortalaması yerine toplam conversion_value / toplam spend
    üzerinden aggregate_metric_queryset ile yeniden hesaplanır.
    """

    agg = aggregate_metric_queryset(CampaignMetricHistory.objects.filter(campaign=campaign))

    spend = d(agg.get("spend"))
    conversion_value = d(agg.get("conversion_value"))
    roas = d(agg.get("roas"))

    metrics = {
        "spend": spend,
        "budget": d(
            getattr(campaign, "daily_budget", 0)
            or getattr(campaign, "lifetime_budget", 0)
            or getattr(campaign, "budget", 0)
        ),
        "conversions": d(agg.get("conversions")),
        "conversion_value": conversion_value,
        "ctr": d(agg.get("ctr")),
        "cpc": d(agg.get("cpc")),
        "cpm": d(agg.get("cpm")),
        "roas": roas,
    }

    roas_score = score_roas(metrics["roas"])
    ctr_score = score_ctr(metrics["ctr"])
    cpc_score = score_cpc(metrics["cpc"])
    conversion_score = Decimal("80") if metrics["conversions"] > 0 else Decimal("20")

    octo_score = (
        roas_score * Decimal("0.40")
        + ctr_score * Decimal("0.25")
        + cpc_score * Decimal("0.20")
        + conversion_score * Decimal("0.15")
    )

    status, risk_level = status_from_score(octo_score, metrics["roas"])
    texts = build_texts(campaign, metrics, status, risk_level)

    analysis = CampaignOctoAnalysis.objects.create(
        campaign=campaign,
        user=user,
        octo_score=octo_score.quantize(Decimal("0.01")),
        status=status,
        risk_level=risk_level,
        roas=metrics["roas"].quantize(Decimal("0.01")),
        ctr=metrics["ctr"].quantize(Decimal("0.01")),
        cpc=metrics["cpc"].quantize(Decimal("0.01")),
        cpm=metrics["cpm"].quantize(Decimal("0.01")),
        spend=metrics["spend"].quantize(Decimal("0.01")),
        budget=metrics["budget"].quantize(Decimal("0.01")),
        conversions=metrics["conversions"].quantize(Decimal("0.01")),
        conversion_value=metrics["conversion_value"].quantize(Decimal("0.01")),
        roas_score=roas_score,
        ctr_score=ctr_score,
        cpc_score=cpc_score,
        conversion_score=conversion_score,
        analysis_text=texts["analysis_text"],
        source=source,
    )

    priority = "high" if risk_level in ("high", "critical") else "medium"
    if status in ("excellent", "good"):
        priority = "low"

    recommendation = CampaignOctoRecommendation.objects.create(
        campaign=campaign,
        analysis=analysis,
        user=user,
        summary=texts["summary"],
        strengths=texts["strengths"],
        weaknesses=texts["weaknesses"],
        recommendations=texts["recommendations"],
        expected_impact=texts["expected_impact"],
        priority=priority,
        source=source,
    )

    return analysis, recommendation
