from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from core.models import Ad, AdMetricHistory, HealthCenterAIAnalysis


class Command(BaseCommand):
    help = "Demo kullanicisi icin reklam sagligi merkezi senaryo cesitliligi olusturur."

    scenarios = [
        ("Sağlıklı Ölçekleme", {"ctr": 3.4, "spend": 260, "conversions": 8.0, "value": 3600, "freq": 1.8, "eng": 5.4}),
        ("Düşük CTR", {"ctr": 0.55, "spend": 210, "conversions": 1.0, "value": 420, "freq": 2.2, "eng": 1.1}),
        ("Yüksek CPA", {"ctr": 2.6, "spend": 960, "conversions": 2.0, "value": 940, "freq": 2.4, "eng": 3.2}),
        ("Düşük ROAS", {"ctr": 2.9, "spend": 780, "conversions": 5.0, "value": 520, "freq": 2.0, "eng": 3.8}),
        ("Kreatif Yorgunluğu", {"ctr": 1.15, "spend": 520, "conversions": 3.0, "value": 900, "freq": 6.8, "eng": 1.7}),
        ("Tıklama Var Satış Yok", {"ctr": 3.1, "spend": 430, "conversions": 0.0, "value": 0, "freq": 2.6, "eng": 4.1}),
        ("Etkileşim Zayıf", {"ctr": 1.8, "spend": 310, "conversions": 2.0, "value": 760, "freq": 2.1, "eng": 0.35}),
        ("Pahalı Tıklama", {"ctr": 0.85, "spend": 640, "conversions": 1.0, "value": 300, "freq": 3.1, "eng": 1.4}),
        ("Kritik Harcama", {"ctr": 0.45, "spend": 1180, "conversions": 0.0, "value": 0, "freq": 5.9, "eng": 0.6}),
        ("İzlenmeli Denge", {"ctr": 1.75, "spend": 360, "conversions": 3.0, "value": 980, "freq": 3.9, "eng": 2.8}),
        ("ROAS Güçlü CTR Zayıf", {"ctr": 0.9, "spend": 280, "conversions": 4.0, "value": 1900, "freq": 2.0, "eng": 1.2}),
        ("CTR Güçlü ROAS Zayıf", {"ctr": 4.2, "spend": 690, "conversions": 3.0, "value": 390, "freq": 2.3, "eng": 5.0}),
    ]

    def handle(self, *args, **options):
        User = get_user_model()
        user = User.objects.filter(username="demo").first()
        if not user:
            self.stderr.write(self.style.ERROR("demo kullanicisi bulunamadi."))
            return

        ads = list(
            Ad.objects.filter(user=user, source_type="OWN")
            .filter(Q(status__iexact="ACTIVE") | Q(is_active=True))
            .select_related("platform_account", "campaign", "ad_group", "creative")
            .order_by("platform_account__platform__code", "platform_account__account_name", "name", "id")[: len(self.scenarios)]
        )
        if len(ads) < len(self.scenarios):
            self.stderr.write(self.style.ERROR("Senaryo icin yeterli demo reklami yok."))
            return

        today = timezone.localdate()
        for ad, (label, scenario) in zip(ads, self.scenarios):
            ad.name = f"Demo Senaryo - {label}"
            ad.status = "ACTIVE"
            ad.is_active = True
            ad.raw_data = {**(ad.raw_data or {}), "demo_health_scenario": label}
            ad.save(update_fields=["name", "status", "is_active", "raw_data", "updated_at"])

            for offset in range(30):
                day = today - timedelta(days=29 - offset)
                wave = Decimal("0.88") + (Decimal(offset % 7) * Decimal("0.035"))
                impressions = int((Decimal("2600") + Decimal(offset * 18)) * wave)
                clicks = max(1, int(Decimal(impressions) * Decimal(str(scenario["ctr"])) / Decimal("100")))
                spend = Decimal(str(scenario["spend"])) * wave
                conversions = Decimal(str(scenario["conversions"])) * (Decimal("0.9") + Decimal(offset % 5) * Decimal("0.04"))
                conversion_value = Decimal(str(scenario["value"])) * (Decimal("0.88") + Decimal(offset % 6) * Decimal("0.045"))
                reach = max(1, int(Decimal(impressions) / Decimal(str(scenario["freq"]))))
                engagement = int(Decimal(impressions) * Decimal(str(scenario["eng"])) / Decimal("100"))
                cpc = spend / Decimal(max(clicks, 1))
                cpm = spend / Decimal(max(impressions, 1)) * Decimal("1000")
                cost_per_conversion = spend / max(conversions, Decimal("1"))
                roas = conversion_value / max(spend, Decimal("1"))
                ctr = Decimal(clicks) / Decimal(max(impressions, 1)) * Decimal("100")
                engagement_rate = Decimal(engagement) / Decimal(max(impressions, 1)) * Decimal("100")

                AdMetricHistory.objects.update_or_create(
                    ad=ad,
                    date=day,
                    defaults={
                        "impressions": impressions,
                        "reach": reach,
                        "frequency": Decimal(str(scenario["freq"])).quantize(Decimal("0.0001")),
                        "clicks": clicks,
                        "link_clicks": int(clicks * 0.82),
                        "unique_clicks": int(clicks * 0.74),
                        "spend": spend.quantize(Decimal("0.01")),
                        "currency": "TRY",
                        "ctr": ctr.quantize(Decimal("0.0001")),
                        "cpc": cpc.quantize(Decimal("0.0001")),
                        "cpm": cpm.quantize(Decimal("0.0001")),
                        "conversions": conversions.quantize(Decimal("0.0001")),
                        "conversion_value": conversion_value.quantize(Decimal("0.01")),
                        "cost_per_conversion": cost_per_conversion.quantize(Decimal("0.0001")),
                        "purchases": conversions.quantize(Decimal("0.0001")),
                        "add_to_cart": (conversions * Decimal("2.4")).quantize(Decimal("0.0001")),
                        "initiate_checkout": (conversions * Decimal("1.55")).quantize(Decimal("0.0001")),
                        "leads": (Decimal(clicks) * Decimal("0.08")).quantize(Decimal("0.0001")),
                        "landing_page_views": int(clicks * 0.68),
                        "outbound_clicks": int(clicks * 0.52),
                        "roas": roas.quantize(Decimal("0.0001")),
                        "likes": int(engagement * 0.58),
                        "comments": int(engagement * 0.09),
                        "shares": int(engagement * 0.12),
                        "saves": int(engagement * 0.16),
                        "video_views": int(impressions * 0.28),
                        "engagement": engagement,
                        "engagement_rate": engagement_rate.quantize(Decimal("0.0001")),
                        "raw_metrics": {"demo": True, "health_scenario": label},
                    },
                )

        HealthCenterAIAnalysis.objects.filter(user=user, days=30, platform_code="", account_id="", status_filter="ACTIVE").delete()
        self.stdout.write(self.style.SUCCESS(f"{len(ads)} demo saglik senaryosu guncellendi."))
