from datetime import timedelta
from decimal import Decimal
import json

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Q, Count

from core.models import (
    OctoTaskRule,
    OctoTaskInstance,
    PlatformAccount,
    Campaign,
    CampaignMetricHistory,
    AdMetricHistory,
    Ad,
)
from core.services.performance_metrics import aggregate_metric_queryset
from core.utils.metric_text import format_tr_decimal


ACTIVE_CAMPAIGN_FILTER = (
    Q(status__iexact="ACTIVE") |
    Q(status__iexact="ENABLED")
)

ACTIVE_AD_FILTER = (
    Q(is_active=True) |
    Q(status__iexact="ACTIVE") |
    Q(status__iexact="ENABLED")
)


def num(value):
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def safe_div(a, b):
    a = num(a)
    b = num(b)
    if b == 0:
        return Decimal("0")
    return a / b


def pct_change(current, previous):
    current = num(current)
    previous = num(previous)

    if previous == 0:
        if current == 0:
            return Decimal("0")
        return Decimal("100")

    return ((current - previous) / previous) * Decimal("100")


def aggregate_metrics(qs):
    data = aggregate_metric_queryset(qs)

    spend = num(data.get("spend"))
    revenue = num(data.get("conversion_value"))
    clicks = num(data.get("clicks"))
    impressions = num(data.get("impressions"))
    conversions = num(data.get("conversions"))
    ctr = num(data.get("ctr"))
    cpc = num(data.get("cpc"))
    roas = num(data.get("roas"))

    conversion_rate = Decimal("0")
    if clicks:
        conversion_rate = safe_div(conversions, clicks) * Decimal("100")

    return {
        "spend": spend,
        "revenue": revenue,
        "clicks": clicks,
        "impressions": impressions,
        "conversions": conversions,
        "ctr": ctr,
        "cpc": cpc,
        "roas": roas,
        "conversion_rate": conversion_rate,
        "frequency": num(data.get("frequency")),
    }


def campaign_metrics(campaign, start_date, end_date):
    campaign_qs = CampaignMetricHistory.objects.filter(
        campaign=campaign,
        date__gte=start_date,
        date__lte=end_date,
    )

    if campaign_qs.exists():
        return aggregate_metrics(campaign_qs), "campaign"

    ad_qs = AdMetricHistory.objects.filter(
        Q(ad__campaign=campaign) | Q(ad__ad_group__campaign=campaign),
        ad__source_type="OWN",
        date__gte=start_date,
        date__lte=end_date,
    )

    return aggregate_metrics(ad_qs), "ad"


def ad_seen_date_filter(prefix, start_date, end_date):
    """Rakip reklamında gerçek görülme tarihini öncelikli kullanır.

    first_seen_at/created_at varsa dönem içinde yakalar. Böylece görev sadece
    gerçek rakip reklam sinyali oluştuğunda üretilir.
    """
    return (
        Q(**{f"{prefix}first_seen_at__date__gte": start_date, f"{prefix}first_seen_at__date__lte": end_date}) |
        Q(**{f"{prefix}created_at__date__gte": start_date, f"{prefix}created_at__date__lte": end_date})
    )


def competitor_name(ad):
    competitor = getattr(ad, "competitor", None)
    if competitor and getattr(competitor, "name", None):
        return competitor.name
    account = getattr(ad, "platform_account", None)
    if account:
        return getattr(account, "account_name", None) or getattr(account, "name", None) or "Rakip firma"
    return "Rakip firma"


def ad_title(ad):
    return (
        getattr(ad, "headline", None)
        or getattr(ad, "name", None)
        or getattr(ad, "primary_text", None)
        or f"Rakip reklam #{ad.id}"
    )


class Command(BaseCommand):
    help = "Gerçek metrik koşullarına göre Octo görevleri üretir."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, default=None)
        parser.add_argument("--account-id", type=int, default=None)
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--campaign-limit", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--clear-open-tasks",
            action="store_true",
            help="Açık OctoTaskInstance kayıtlarını temizler."
        )

    def handle(self, *args, **options):
        user_id = options["user_id"]
        account_id = options["account_id"]
        days = max(int(options["days"] or 7), 1)
        campaign_limit = int(options["campaign_limit"] or 0)
        dry_run = options["dry_run"]
        clear_open_tasks = options["clear_open_tasks"]

        today = timezone.localdate()
        start_date = today - timedelta(days=days - 1)
        prev_end = start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days - 1)

        if clear_open_tasks:
            qs = OctoTaskInstance.objects.filter(status="open")
            if dry_run:
                self.stdout.write(self.style.WARNING(f"DRY-RUN: {qs.count()} açık görev temizlenecekti."))
            else:
                deleted_count, _ = qs.delete()
                self.stdout.write(self.style.SUCCESS(f"Temizlenen açık görev: {deleted_count}"))

        User = get_user_model()
        users = User.objects.all()

        if user_id:
            users = users.filter(id=user_id)

        created_count = 0
        skipped_count = 0
        matched_signal_count = 0
        campaign_count = 0
        competitor_ad_count = 0
        competitor_task_count = 0

        for user in users:
            accounts = (
                PlatformAccount.objects
                .filter(user=user, is_active=True)
                .select_related("platform", "connection")
            )
            if account_id:
                accounts = accounts.filter(id=account_id)

            for account in accounts:
                campaigns = (
                    Campaign.objects
                    .filter(user=user, platform_account=account)
                    .filter(ACTIVE_CAMPAIGN_FILTER)
                    .order_by("-updated_at", "-created_at", "id")
                )

                if campaign_limit:
                    campaigns = campaigns[:campaign_limit]

                for campaign in campaigns:
                    active_ads = (
                        Ad.objects
                        .filter(user=user, source_type="OWN")
                        .filter(ACTIVE_AD_FILTER)
                        .filter(Q(campaign=campaign) | Q(ad_group__campaign=campaign))
                    )

                    if not active_ads.exists():
                        continue

                    campaign_count += 1

                    current, source = campaign_metrics(campaign, start_date, today)
                    previous, _ = campaign_metrics(campaign, prev_start, prev_end)

                    signals = self.detect_signals(current, previous)

                    for signal in signals:
                        matched_signal_count += 1
                        rule = self.find_rule(signal)

                        if not rule:
                            skipped_count += 1
                            continue

                        unique_key = (
                            f"user:{user.id}|"
                            f"account:{account.id}|"
                            f"campaign:{campaign.id}|"
                            f"signal:{signal['key']}|"
                            f"rule:{rule.code}|"
                            f"period:{start_date}_{today}"
                        )

                        existing = OctoTaskInstance.objects.filter(
                            user=user,
                            platform_account=account,
                            campaign=campaign,
                            rule=rule,
                            status__in=["open", "viewed", "snoozed"]
                        ).order_by("-last_detected_at", "-id").first()

                        if existing:
                            if not dry_run:
                                existing.module = rule.module
                                existing.severity = signal.get("severity") or rule.severity
                                existing.title_tr = rule.title_tr
                                existing.message_tr = self.build_message(rule, campaign, signal)
                                existing.action_text_tr = rule.action_text_tr or rule.cta_text
                                existing.priority_score = max(rule.priority_score, signal.get("priority_score", 50))
                                existing.detected_value = signal.get("detected_value")
                                existing.previous_value = signal.get("previous_value")
                                existing.change_percent = signal.get("change_percent")
                                existing.source_period_start = start_date
                                existing.source_period_end = today
                                existing.last_detected_at = timezone.now()
                                existing.save(update_fields=[
                                    "module", "severity", "title_tr", "message_tr", "action_text_tr",
                                    "priority_score", "detected_value", "previous_value", "change_percent",
                                    "source_period_start", "source_period_end", "last_detected_at", "updated_at",
                                ])
                            skipped_count += 1
                            continue

                        if dry_run:
                            created_count += 1
                            self.stdout.write(
                                f"[DRY] {campaign.name} -> {signal['label']} -> {rule.code} / {rule.title_tr}"
                            )
                            continue

                        OctoTaskInstance.objects.create(
                            rule=rule,
                            user=user,
                            platform_connection=getattr(account, "connection", None),
                            platform_account=account,
                            campaign=campaign,
                            module=rule.module,
                            severity=signal.get("severity") or rule.severity,
                            title_tr=rule.title_tr,
                            message_tr=self.build_message(rule, campaign, signal),
                            action_text_tr=rule.action_text_tr or rule.cta_text,
                            title_en=rule.title_en,
                            message_en=rule.message_en,
                            action_text_en=rule.action_text_en,
                            priority_score=max(rule.priority_score, signal.get("priority_score", 50)),
                            detected_value=signal.get("detected_value"),
                            previous_value=signal.get("previous_value"),
                            change_percent=signal.get("change_percent"),
                            source_period_start=start_date,
                            source_period_end=today,
                            unique_key=unique_key,
                            first_detected_at=timezone.now(),
                            last_detected_at=timezone.now(),
                        )

                        created_count += 1


                competitor_result = self.generate_competitor_tasks_for_account(
                    user=user,
                    account=account,
                    start_date=start_date,
                    today=today,
                    prev_start=prev_start,
                    prev_end=prev_end,
                    dry_run=dry_run,
                )
                competitor_ad_count += competitor_result["ads"]
                competitor_task_count += competitor_result["created"]
                created_count += competitor_result["created"]
                skipped_count += competitor_result["skipped"]
                matched_signal_count += competitor_result["signals"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN: Veritabanına yazılmadı."))

        self.stdout.write(self.style.SUCCESS("Gerçek koşullu Octo görev üretimi tamamlandı."))
        self.stdout.write(f"İşlenen aktif kampanya: {campaign_count}")
        self.stdout.write(f"İşlenen rakip reklam: {competitor_ad_count}")
        self.stdout.write(f"Oluşturulan rakip görevi: {competitor_task_count}")
        self.stdout.write(f"Yakalanan sinyal: {matched_signal_count}")
        self.stdout.write(f"Oluşturulan: {created_count}")
        self.stdout.write(f"Atlanan: {skipped_count}")
        self.stdout.write("OCTO_SUMMARY_JSON=" + json.dumps({
            "campaigns_evaluated": campaign_count,
            "competitor_ads_evaluated": competitor_ad_count,
            "competitor_tasks_created": competitor_task_count,
            "signals_matched": matched_signal_count,
            "tasks_created": created_count,
            "tasks_skipped": skipped_count,
        }, ensure_ascii=False))

    def generate_competitor_tasks_for_account(self, user, account, start_date, today, prev_start, prev_end, dry_run=False):
        """Rakip reklamlarını gerçek koşullara göre OctoTaskInstance'a dönüştürür.

        Gösterim amaçlı satır üretmez. Sadece dönem içinde yeni görülen veya
        rakip baskısı artan COMPETITOR reklamlarından gerçek instance açar.
        """
        result = {"ads": 0, "signals": 0, "created": 0, "skipped": 0}

        current_ads = (
            Ad.objects
            .filter(user=user, source_type="COMPETITOR", platform_account=account)
            .filter(ad_seen_date_filter("", start_date, today))
            .select_related("competitor", "platform_account", "platform_account__connection")
            .order_by("-first_seen_at", "-created_at", "-id")
        )

        result["ads"] = current_ads.count()
        if not current_ads.exists():
            return result

        previous_count = (
            Ad.objects
            .filter(user=user, source_type="COMPETITOR", platform_account=account)
            .filter(ad_seen_date_filter("", prev_start, prev_end))
            .count()
        )
        current_count = result["ads"]
        competitor_burst = current_count >= 5 or pct_change(current_count, previous_count) >= Decimal("50")

        for ad in current_ads:
            signals = self.detect_competitor_signals(ad, competitor_burst, current_count, previous_count)
            for signal in signals:
                result["signals"] += 1
                rule = self.find_competitor_rule(signal)
                if not rule:
                    result["skipped"] += 1
                    continue

                unique_key = (
                    f"user:{user.id}|"
                    f"account:{account.id}|"
                    f"competitor_ad:{ad.id}|"
                    f"signal:{signal['key']}|"
                    f"rule:{rule.code}|"
                    f"period:{start_date}_{today}"
                )

                exists = OctoTaskInstance.objects.filter(
                    unique_key=unique_key,
                    status__in=["open", "viewed", "snoozed"],
                ).exists()

                if exists:
                    result["skipped"] += 1
                    continue

                if dry_run:
                    result["created"] += 1
                    self.stdout.write(
                        f"[DRY][RAKİP] {competitor_name(ad)} -> {signal['label']} -> {rule.code} / {rule.title_tr}"
                    )
                    continue

                OctoTaskInstance.objects.create(
                    rule=rule,
                    user=user,
                    platform_connection=getattr(account, "connection", None),
                    platform_account=account,
                    ad=ad,
                    module="competitor",
                    severity=signal.get("severity") or rule.severity,
                    title_tr=rule.title_tr,
                    message_tr=self.build_competitor_message(rule, ad, signal),
                    action_text_tr=rule.action_text_tr or rule.cta_text or "Rakip reklamını incele",
                    title_en=rule.title_en,
                    message_en=rule.message_en,
                    action_text_en=rule.action_text_en,
                    priority_score=max(rule.priority_score, signal.get("priority_score", 70)),
                    detected_value=signal.get("detected_value"),
                    previous_value=signal.get("previous_value"),
                    change_percent=signal.get("change_percent"),
                    source_period_start=start_date,
                    source_period_end=today,
                    unique_key=unique_key,
                    first_detected_at=timezone.now(),
                    last_detected_at=timezone.now(),
                )
                result["created"] += 1

        return result

    def detect_competitor_signals(self, ad, competitor_burst, current_count, previous_count):
        signals = []
        base = {
            "key": "competitor_new_ad",
            "label": "Rakip yeni reklam yayına aldı",
            "severity": "warning",
            "priority_score": 82,
            "keywords": ["Rakip", "yeni reklam", "reklam", "istihbarat"],
            "detected_value": Decimal("1"),
            "previous_value": Decimal("0"),
            "change_percent": Decimal("100"),
        }
        signals.append(base)

        if competitor_burst:
            signals.append({
                "key": "competitor_ad_burst",
                "label": "Rakip reklam baskısı arttı",
                "severity": "critical",
                "priority_score": 91,
                "keywords": ["Rakip", "baskı", "rekabet", "yeni reklam"],
                "detected_value": Decimal(str(current_count)),
                "previous_value": Decimal(str(previous_count)),
                "change_percent": pct_change(current_count, previous_count),
            })

        if getattr(ad, "landing_url", None):
            signals.append({
                "key": "competitor_landing_page_signal",
                "label": "Rakip landing page sinyali yakalandı",
                "severity": "opportunity",
                "priority_score": 78,
                "keywords": ["Rakip", "landing", "sayfa", "fırsat"],
                "detected_value": Decimal("1"),
                "previous_value": Decimal("0"),
                "change_percent": Decimal("100"),
            })

        return signals

    def find_competitor_rule(self, signal):
        signal_key = signal.get("key")
        title_map = {
            "competitor_new_ad": ["Rakip", "Yeni Reklam", "Rakip Reklam"],
            "competitor_ad_burst": ["Rakip Baskısı", "Rakip", "Rekabet"],
            "competitor_landing_page_signal": ["Rakip", "Landing", "Sayfa", "Fırsat"],
        }

        base_qs = OctoTaskRule.objects.filter(
            is_active=True,
            module="competitor",
            severity=signal.get("severity", "warning"),
        )

        for title in title_map.get(signal_key, []):
            rule = base_qs.filter(title_tr__icontains=title).order_by("-priority_score", "code").first()
            if rule:
                return rule

        keywords = signal.get("keywords") or []
        query = Q()
        for keyword in keywords:
            query |= Q(title_tr__icontains=keyword)
            query |= Q(message_tr__icontains=keyword)
            query |= Q(action_text_tr__icontains=keyword)
            query |= Q(user_condition__icontains=keyword)
            query |= Q(root_cause__icontains=keyword)
            query |= Q(expected_result__icontains=keyword)

        if query:
            rule = base_qs.filter(query).order_by("-priority_score", "code").first()
            if rule:
                return rule

        return base_qs.order_by("-priority_score", "code").first()

    def build_competitor_message(self, rule, ad, signal):
        base = rule.message_tr or rule.user_condition or rule.title_tr
        name = competitor_name(ad)
        title = ad_title(ad)
        landing_url = getattr(ad, "landing_url", None) or "-"
        ad_format = getattr(ad, "ad_format", None) or "-"

        detail = (
            f"\n\nRakip firma: {name}"
            f"\nRakip reklam: {title}"
            f"\nTespit edilen durum: {signal['label']}"
            f"\nReklam formatı: {ad_format}"
            f"\nLanding URL: {landing_url}"
            f"\nMevcut değer: {format_tr_decimal(signal.get('detected_value'))}"
            f"\nÖnceki değer: {format_tr_decimal(signal.get('previous_value'))}"
            f"\nDeğişim: %{format_tr_decimal(signal.get('change_percent'))}"
        )
        return f"{base}{detail}"

    def detect_signals(self, current, previous):
        signals = []

        # Geçmiş dönemde veri vardı, mevcut dönemde veri yok.
        # Bu durum "ROAS düştü" değil; "veri akışı / trafik durmuş olabilir" görevidir.
        if current["spend"] == 0 and previous["spend"] > 0:
            signals.append({
                "key": "traffic_or_data_stopped",
                "label": "Kampanya verisi durmuş görünüyor",
                "severity": "critical",
                "priority_score": 97,
                "keywords": [
                    "Veriler Tutarsız Görünüyor",
                    "veri",
                    "durdu",
                    "trafik",
                    "risk",
                ],
                "detected_value": current["spend"],
                "previous_value": previous["spend"],
                "change_percent": Decimal("-100"),
            })

            # Veri yokken diğer performans sinyallerini hesaplamak yanıltıcı olur.
            return signals

        roas_delta = pct_change(current["roas"], previous["roas"])
        ctr_delta = pct_change(current["ctr"], previous["ctr"])
        cpc_delta = pct_change(current["cpc"], previous["cpc"])
        spend_delta = pct_change(current["spend"], previous["spend"])
        conversion_rate_delta = pct_change(current["conversion_rate"], previous["conversion_rate"])

        if current["spend"] > 0 and current["roas"] > 0 and roas_delta <= Decimal("-30"):
            signals.append({
                "key": "roas_drop",
                "label": "ROAS düşüşü",
                "severity": "critical",
                "priority_score": 95,
                "keywords": ["Gelir Verimi Düştü", "ROAS", "getiri", "gelir"],
                "detected_value": current["roas"],
                "previous_value": previous["roas"],
                "change_percent": roas_delta,
            })

        if current["impressions"] > 0 and current["ctr"] > 0 and ctr_delta <= Decimal("-25"):
            signals.append({
                "key": "ctr_drop",
                "label": "İlgi düşüşü",
                "severity": "warning",
                "priority_score": 85,
                "keywords": ["ilgi", "tıklanma", "CTR", "dikkat"],
                "detected_value": current["ctr"],
                "previous_value": previous["ctr"],
                "change_percent": ctr_delta,
            })

        if current["clicks"] > 0 and current["cpc"] > 0 and cpc_delta >= Decimal("30"):
            signals.append({
                "key": "cpc_increase",
                "label": "Tıklama maliyeti yükseldi",
                "severity": "warning",
                "priority_score": 84,
                "keywords": ["Tıklama Maliyeti", "Sonuç Maliyeti", "maliyet", "CPC"],
                "detected_value": current["cpc"],
                "previous_value": previous["cpc"],
                "change_percent": cpc_delta,
            })

        if current["spend"] > previous["spend"] and spend_delta >= Decimal("30") and roas_delta <= Decimal("-15"):
            signals.append({
                "key": "spend_up_roas_down",
                "label": "Harcama artıyor ama verim düşüyor",
                "severity": "critical",
                "priority_score": 94,
                "keywords": ["bütçe", "harcama", "Gelir Verimi Düştü", "verim"],
                "detected_value": current["spend"],
                "previous_value": previous["spend"],
                "change_percent": spend_delta,
            })

        if current["ctr"] >= Decimal("1.5") and current["conversion_rate"] < Decimal("0.5") and current["clicks"] >= 20:
            signals.append({
                "key": "clicks_no_conversion",
                "label": "İlgi satışa dönmüyor",
                "severity": "critical",
                "priority_score": 92,
                "keywords": ["İlgi Satışa Dönmüyor", "satışa dönmüyor", "dönüşüm", "ürün sayfası"],
                "detected_value": current["conversion_rate"],
                "previous_value": previous["conversion_rate"],
                "change_percent": conversion_rate_delta,
            })

        if current["roas"] >= Decimal("4") and current["spend"] > 0:
            signals.append({
                "key": "scale_opportunity",
                "label": "Büyütme fırsatı",
                "severity": "opportunity",
                "priority_score": 80,
                "keywords": ["bütçe artır", "fırsat", "ölçek", "büyüt"],
                "detected_value": current["roas"],
                "previous_value": previous["roas"],
                "change_percent": roas_delta,
            })

        if current["frequency"] >= Decimal("5") and ctr_delta <= Decimal("-15"):
            signals.append({
                "key": "creative_fatigue",
                "label": "Reklam yorulması",
                "severity": "warning",
                "priority_score": 88,
                "keywords": ["yorgun", "kreatif", "creative", "dikkat"],
                "detected_value": current["frequency"],
                "previous_value": previous["frequency"],
                "change_percent": ctr_delta,
            })

        if current["spend"] > 0 and current["revenue"] == 0 and current["clicks"] >= 20:
            signals.append({
                "key": "budget_waste",
                "label": "Bütçe boşa harcanıyor olabilir",
                "severity": "critical",
                "priority_score": 96,
                "keywords": ["bütçe", "boşa", "risk", "Gelir Verimi Düştü"],
                "detected_value": current["spend"],
                "previous_value": previous["spend"],
                "change_percent": spend_delta,
            })

        return signals

    def find_rule(self, signal):
        signal_key = signal.get("key")

        # Önce sinyal türüne özel başlık eşleştirmesi yapılır.
        # Böylece her sinyal en yüksek puanlı rastgele kurala değil,
        # kendi anlamına en yakın kurala bağlanır.
        title_map = {
            "traffic_or_data_stopped": [
                "Veriler Tutarsız Görünüyor",
                "Kampanya Verisi Durdu",
                "Veri Akışı Durdu",
                "Veri Akışı",
            ],
            "roas_drop": [
                "Gelir Verimi Düştü",
                "ROAS Düştü",
                "Getiri Düştü",
            ],
            "ctr_drop": [
                "Reklam CTR",
                "CTR",
                "Reklam İlgi Kaybediyor",
                "İlgi Düştü",
                "Tıklanma Düştü",
            ],
            "cpc_increase": [
                "Sonuç Maliyeti Yükseldi",
                "Tıklama Maliyeti Yükseldi",
                "Maliyet Yükseldi",
            ],
            "spend_up_roas_down": [
                "Harcama Artıyor",
                "Bütçe Verimi Düştü",
                "Gelir Verimi Düştü",
            ],
            "clicks_no_conversion": [
                "İlgi Satışa Dönmüyor",
                "Tıklama Satışa Dönmüyor",
                "Dönüşüm Sorunu",
            ],
            "scale_opportunity": [
                "Ölçekleme Fırsatı",
                "Büyütme Fırsatı",
                "Bütçe Artırma Fırsatı",
                "Ölçeklenebilir",
                "Fırsat",
            ],
            "creative_fatigue": [
                "Creative Yorgun",
                "Yorgun",
                "Reklam Yorulması",
                "Kreatif Yoruldu",
                "Yorgunluk",
            ],
            "budget_waste": [
                "Harcama Var Dönüşüm Yok",
                "Bütçe Boşa Harcanıyor",
                "Bütçe Riski",
                "Boşa Harcama",
            ],
        }

        severity = signal.get("severity", "warning")
        severity_candidates = {
            "scale_opportunity": ["opportunity", "info", "warning"],
            "creative_fatigue": ["warning", "critical"],
            "budget_waste": ["critical", "warning"],
        }.get(signal_key, [severity])

        base_qs = OctoTaskRule.objects.filter(
            is_active=True,
            severity__in=severity_candidates,
        )

        for title in title_map.get(signal_key, []):
            rule = (
                base_qs
                .filter(title_tr__icontains=title)
                .order_by("-priority_score", "code")
                .first()
            )
            if rule:
                return rule

        keywords = signal.get("keywords") or []
        query = Q()

        for keyword in keywords:
            query |= Q(title_tr__icontains=keyword)
            query |= Q(message_tr__icontains=keyword)
            query |= Q(action_text_tr__icontains=keyword)
            query |= Q(user_condition__icontains=keyword)
            query |= Q(root_cause__icontains=keyword)
            query |= Q(expected_result__icontains=keyword)

        if query:
            rule = (
                base_qs
                .filter(query)
                .order_by("-priority_score", "code")
                .first()
            )
            if rule:
                return rule

        return (
            base_qs
            .order_by("-priority_score", "code")
            .first()
        )

    def build_message(self, rule, campaign, signal):
        base = rule.message_tr or rule.user_condition or rule.title_tr

        metric_line = (
            f"\n\nKampanya: {campaign.name}"
            f"\nTespit edilen durum: {signal['label']}"
            f"\nMevcut değer: {format_tr_decimal(signal.get('detected_value'))}"
            f"\nÖnceki değer: {format_tr_decimal(signal.get('previous_value'))}"
            f"\nDeğişim: %{format_tr_decimal(signal.get('change_percent'))}"
        )

        return f"{base}{metric_line}"
