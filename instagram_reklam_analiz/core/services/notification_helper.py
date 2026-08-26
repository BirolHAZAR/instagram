# core/services/notification_helper.py
"""Merkezi bildirim yardımcısı.

Tüm sistem bildirimleri bu dosyadan üretilir. Amaç:
- View, signal ve service katmanlarında aynı formatı kullanmak
- Aynı bildirimin kısa sürede tekrar tekrar oluşmasını engellemek
- Bildirim üretimi hata alsa bile ana işlemi bozmamak
"""

import logging
from datetime import timedelta
from django.utils import timezone
from core.models.notification import Notification
from core.services.activity_service import object_activity_link, record_activity_from_notification
from core.services.notification_preferences import category_from_title, is_in_app_allowed

logger = logging.getLogger(__name__)


class NotificationHelper:
    DEFAULT_LINK = "/"

    @staticmethod
    def _category_from_title(title, level):
        return category_from_title(title, level)
        title_lower = (title or "").lower()
        if level == "critical":
            return "critical"
        if "rakip" in title_lower:
            return "competitor"
        if "ai" in title_lower:
            return "ai"
        if "kampanya" in title_lower:
            return "campaign"
        if "optimizasyon" in title_lower or "bütçe" in title_lower:
            return "optimization"
        return "system"

    @staticmethod
    def _is_allowed_by_preferences(user, title, level):
        return is_in_app_allowed(user, title, level)
        try:
            prefs, _ = user.notification_preferences.__class__.objects.get_or_create(user=user)
        except Exception:
            try:
                from core.models.notification_settings import NotificationPreference
                prefs, _ = NotificationPreference.objects.get_or_create(user=user)
            except Exception:
                return True

        if not prefs.in_app_enabled:
            return False

        category = NotificationHelper._category_from_title(title, level)
        checks = {
            "critical": prefs.critical_notifications,
            "competitor": prefs.competitor_notifications,
            "ai": prefs.ai_notifications,
            "campaign": prefs.campaign_notifications,
            "optimization": prefs.optimization_notifications,
            "system": prefs.system_notifications,
        }
        return checks.get(category, True)

    @staticmethod
    def notify(user, title, message, level="info", icon="🔔", link=None, dedupe_minutes=2):
        if not user or not getattr(user, "is_authenticated", False):
            return None
        link = link or NotificationHelper.DEFAULT_LINK
        try:
            if not NotificationHelper._is_allowed_by_preferences(user, title, level):
                return None
            if dedupe_minutes:
                since = timezone.now() - timedelta(minutes=dedupe_minutes)
                if Notification.objects.filter(user=user, title=title, message=message, link=link, created_at__gte=since).exists():
                    return None
            notification = Notification.objects.create(
                user=user,
                title=title,
                message=message,
                level=level,
                icon=icon,
                link=link,
                is_read=False,
            )
            record_activity_from_notification(notification)
            return notification
        except Exception as exc:
            logger.exception("Bildirim oluşturulamadı: %s", exc)
            return None

    # -------------------- Rakip --------------------
    @staticmethod
    def competitor_added(user, rakip):
        name = getattr(rakip, "name", None) or getattr(rakip, "platform_identifier", "Yeni rakip")
        return NotificationHelper.notify(user, "Yeni rakip eklendi", f"{name} rakip listenize eklendi.", "success", "🕵️", object_activity_link(rakip) or "/rakip-analiz/")

    @staticmethod
    def competitor_updated(user, rakip):
        name = getattr(rakip, "name", None) or getattr(rakip, "platform_identifier", "Rakip")
        return NotificationHelper.notify(user, "Rakip bilgisi güncellendi", f"{name} rakibinin bilgileri güncellendi.", "info", "🕵️", object_activity_link(rakip) or "/rakip-analiz/", dedupe_minutes=10)

    @staticmethod
    def competitor_status_changed(user, rakip, is_active):
        name = getattr(rakip, "name", None) or getattr(rakip, "platform_identifier", "Rakip")
        return NotificationHelper.notify(
            user,
            "Rakip aktif edildi" if is_active else "Rakip pasif edildi",
            f"{name} rakibi {'aktif edildi' if is_active else 'pasif edildi'}.",
            "success" if is_active else "warning",
            "🕵️",
            "/rakip-analiz/",
            dedupe_minutes=2,
        )

    @staticmethod
    def competitor_deleted(user, name):
        return NotificationHelper.notify(user, "Rakip silindi", f"{name} rakip listenizden kaldırıldı.", "warning", "🗑️", "/rakip-analiz/", dedupe_minutes=2)

    @staticmethod
    def competitor_ad_found(user, ad):
        name = getattr(ad, "name", None) or getattr(ad, "title", None) or "Yeni rakip reklamı"
        return NotificationHelper.notify(user, "Yeni rakip reklamı bulundu", f"{name[:80]} sisteme eklendi.", "info", "📢", object_activity_link(ad) or "/rakip-reklam-paneli/", dedupe_minutes=5)

    @staticmethod
    def competitor_ads_synced(user, rakip, count):
        name = getattr(rakip, "name", None) or getattr(rakip, "platform_identifier", "Rakip")
        return NotificationHelper.notify(user, "Rakip reklamları güncellendi", f"{name} için {count} reklam güncellendi.", "success", "🔄", "/rakip-reklam-paneli/", dedupe_minutes=1)

    # -------------------- Platform / hesap --------------------
    @staticmethod
    def platform_account_connected(user, account, created=True):
        platform = getattr(getattr(account, "platform", None), "name", "Platform")
        account_name = getattr(account, "account_name", None) or getattr(account, "account_id", "hesap")
        return NotificationHelper.notify(user, "Platform hesabı bağlandı" if created else "Platform hesabı güncellendi", f"{platform} - {account_name} hesabı {'bağlandı' if created else 'güncellendi'}.", "success" if created else "info", "🔌", "/hesap-ekle/")

    @staticmethod
    def platform_account_status_changed(user, account, is_active):
        platform = getattr(getattr(account, "platform", None), "name", "Platform")
        account_name = getattr(account, "account_name", None) or getattr(account, "account_id", "hesap")
        return NotificationHelper.notify(user, "Platform hesabı aktif" if is_active else "Platform hesabı pasif", f"{platform} - {account_name} hesabı {'aktif edildi' if is_active else 'pasif edildi'}.", "success" if is_active else "warning", "🔌", "/hesap-ekle/", dedupe_minutes=5)

    @staticmethod
    def instagram_account_added(user, account):
        username = getattr(account, "username", "Instagram hesabı")
        return NotificationHelper.notify(user, "Instagram hesabı eklendi", f"@{username} hesabı başarıyla eklendi.", "success", "📸", "/instagram/")

    @staticmethod
    def instagram_account_status_changed(user, account, is_active):
        username = getattr(account, "username", "Instagram hesabı")
        return NotificationHelper.notify(user, "Instagram hesabı aktif" if is_active else "Instagram hesabı pasif", f"@{username} hesabı {'aktif edildi' if is_active else 'pasif edildi'}.", "success" if is_active else "warning", "📸", "/instagram/", dedupe_minutes=5)

    @staticmethod
    def instagram_post_status_changed(user, post, old_status, new_status):
        username = getattr(getattr(post, "instagram_account", None), "username", "Instagram")
        level = "success" if new_status == "published" else "warning" if new_status == "failed" else "info"
        icon = "✅" if new_status == "published" else "❌" if new_status == "failed" else "⏳"
        return NotificationHelper.notify(user, "Instagram paylaşım durumu değişti", f"@{username} paylaşımı: {old_status} → {new_status}", level, icon, "/instagram/", dedupe_minutes=2)

    # -------------------- Reklam / kampanya --------------------
    @staticmethod
    def campaign_created(user, campaign):
        name = getattr(campaign, "campaign_name", "Yeni kampanya")
        return NotificationHelper.notify(user, "Yeni kampanya oluşturuldu", f"{name} kampanyası oluşturuldu.", "success", "🎯", object_activity_link(campaign) or "/campaigns/")

    @staticmethod
    def campaign_status_changed(user, campaign, old_status, new_status):
        name = getattr(campaign, "campaign_name", "Kampanya")
        level = "warning" if new_status in ["paused", "ended", "cancelled"] else "success" if new_status in ["active", "sent_to_instagram"] else "info"
        return NotificationHelper.notify(user, "Kampanya durumu değişti", f"{name}: {old_status} → {new_status}", level, "📣", object_activity_link(campaign) or "/campaigns/", dedupe_minutes=2)

    @staticmethod
    def campaign_budget_changed(user, campaign, old_budget, new_budget):
        name = getattr(campaign, "campaign_name", "Kampanya")
        return NotificationHelper.notify(user, "Kampanya bütçesi değişti", f"{name}: ₺{old_budget} → ₺{new_budget}", "info", "💰", object_activity_link(campaign) or "/campaigns/", dedupe_minutes=2)

    @staticmethod
    def campaign_manual_override(user, campaign):
        name = getattr(campaign, "campaign_name", "Kampanya")
        return NotificationHelper.notify(user, "Kampanyaya manuel müdahale edildi", f"{name} kampanyasında manuel durum değişikliği yapıldı.", "warning", "✋", object_activity_link(campaign) or "/campaigns/", dedupe_minutes=2)

    @staticmethod
    def ad_added(user, ad):
        name = getattr(ad, "name", None) or getattr(ad, "title", None) or "Yeni reklam"
        return NotificationHelper.notify(user, "Yeni reklam eklendi", f"{name[:80]} sisteme eklendi.", "success", "📢", object_activity_link(ad) or "/reklam-raporu/", dedupe_minutes=5)

    @staticmethod
    def ad_status_changed(user, ad, old_status, new_status):
        name = getattr(ad, "name", None) or "Reklam"
        level = "success" if new_status == "active" else "warning" if new_status in ["paused", "completed"] else "info"
        return NotificationHelper.notify(user, "Reklam durumu değişti", f"{name[:70]}: {old_status} → {new_status}", level, "📢", object_activity_link(ad) or "/reklam-raporu/", dedupe_minutes=5)

    @staticmethod
    def ad_performance_warning(user, ad):
        name = getattr(ad, "name", None) or "Reklam"
        score = getattr(ad, "performance_score", 0)
        return NotificationHelper.notify(user, "Reklam performansı düşük", f"{name[:70]} performans skoru kritik seviyede: {score}/100.", "warning", "📉", object_activity_link(ad) or "/ai/dashboard/", dedupe_minutes=60)

    @staticmethod
    def metric_anomaly(user, obj, reason=None, competitor=False):
        reason = reason or getattr(obj, "anomaly_reason", None) or "Metriklerde olağan dışı değişim tespit edildi."
        return NotificationHelper.notify(user, "Rakip reklam metriğinde anomali" if competitor else "Reklam metriğinde anomali", reason[:160], "warning", "📊", object_activity_link(obj) or ("/rakip-reklam-hareketleri/" if competitor else "/reklam-hareketleri/"), dedupe_minutes=60)

    # -------------------- AI / Creative / Anomali --------------------
    @staticmethod
    def ai_analysis_created(user, analysis):
        name = getattr(analysis, "reklam_adi", None) or "Reklam"
        score = getattr(analysis, "overall_score", None)
        suffix = f" Genel skor: {score}/100." if score is not None else ""
        level = "warning" if score is not None and score < 35 else "success"
        return NotificationHelper.notify(user, "AI reklam analizi hazır", f"{name[:70]} için AI analiz oluşturuldu.{suffix}", level, "🤖", "/ai/dashboard/", dedupe_minutes=5)

    @staticmethod
    def campaign_ai_analysis_created(user, analysis):
        campaign = getattr(analysis, "campaign", None)
        name = getattr(campaign, "campaign_name", None) or "Kampanya"
        score = getattr(analysis, "performance_score", 0)
        level = "warning" if score and score < 35 else "success"
        return NotificationHelper.notify(user, "AI kampanya analizi hazır", f"{name} için AI analiz oluşturuldu. Skor: {score}/100.", level, "🤖", "/ai/dashboard/", dedupe_minutes=5)

    @staticmethod
    def creative_project_completed(user, project):
        name = getattr(project, "name", None) or getattr(project, "title", None) or "Creative projeniz"
        return NotificationHelper.notify(user, "Creative Studio projesi tamamlandı", f"{name} tamamlandı.", "success", "🎨", object_activity_link(project) or "/creative-studio/", dedupe_minutes=2)

    @staticmethod
    def creative_project_status_changed(user, project, old_status, new_status):
        name = getattr(project, "name", None) or "Creative proje"
        level = "success" if new_status in ["approved", "published"] else "warning" if new_status == "rejected" else "info"
        return NotificationHelper.notify(user, "Creative proje durumu değişti", f"{name}: {old_status} → {new_status}", level, "🎨", object_activity_link(project) or "/creative-studio/", dedupe_minutes=2)

    @staticmethod
    def high_score_content(user, content):
        project = getattr(content, "project", None)
        name = getattr(project, "name", "Creative proje")
        score = getattr(content, "ai_score", 0)
        return NotificationHelper.notify(user, "Yüksek skorlu içerik üretildi", f"{name} içinde {score}/100 skorlu yeni içerik üretildi.", "success", "🏆", "/creative-studio/", dedupe_minutes=30)

    @staticmethod
    def anomaly_detected(user, anomaly):
        title = getattr(anomaly, "title", None) or getattr(anomaly, "message", None) or "Yeni anomali tespit edildi"
        severity = getattr(anomaly, "severity", "medium")
        level = "critical" if severity == "critical" else "warning" if severity in ["high", "medium", "error"] else "info"
        return NotificationHelper.notify(user, "Anomali tespit edildi", title[:160], level, "🚨" if level == "critical" else "⚠️", object_activity_link(anomaly) or "/anomaly-dashboard/", dedupe_minutes=30)

    @staticmethod
    def opportunity_found(user, opportunity):
        title = getattr(opportunity, "title", "Yeni fırsat penceresi")
        return NotificationHelper.notify(user, "Yeni fırsat penceresi bulundu", title[:160], "success", "🌟", "/anomaly-dashboard/", dedupe_minutes=30)

    @staticmethod
    def system_error(user, error):
        message = getattr(error, "short_message", None) or getattr(error, "message", "Sistem hatası")
        severity = getattr(error, "severity", "error")
        level = "critical" if severity == "critical" else "warning" if severity in ["error", "warning"] else "info"
        return NotificationHelper.notify(user, "Sistem uyarısı", message[:160], level, "🚨" if level == "critical" else "⚠️", "/", dedupe_minutes=60)

    # -------------------- Finans / üyelik / rapor --------------------
    @staticmethod
    def payment_completed(user, payment):
        plan = getattr(getattr(payment, "plan", None), "display_name", "Paket")
        amount = getattr(payment, "amount", "")
        return NotificationHelper.notify(user, "Ödeme başarılı", f"{plan} ödemeniz tamamlandı. Tutar: ₺{amount}", "success", "💳", "/membership/", dedupe_minutes=5)

    @staticmethod
    def payment_failed(user, payment):
        plan = getattr(getattr(payment, "plan", None), "display_name", "Paket")
        return NotificationHelper.notify(user, "Ödeme başarısız", f"{plan} ödemeniz tamamlanamadı. Lütfen ödeme bilgilerinizi kontrol edin.", "critical", "💳", "/membership/", dedupe_minutes=30)

    @staticmethod
    def payment_refunded(user, payment):
        amount = getattr(payment, "amount", "")
        return NotificationHelper.notify(user, "Ödeme iade edildi", f"₺{amount} tutarındaki ödeme iade edildi.", "info", "↩️", "/membership/", dedupe_minutes=5)

    @staticmethod
    def subscription_activated(user, subscription):
        plan = getattr(getattr(subscription, "plan", None), "display_name", "Paket")
        return NotificationHelper.notify(user, "Abonelik aktif edildi", f"{plan} aboneliğiniz aktif edildi.", "success", "⭐", "/membership/", dedupe_minutes=5)

    @staticmethod
    def subscription_deactivated(user, subscription):
        plan = getattr(getattr(subscription, "plan", None), "display_name", "Paket")
        return NotificationHelper.notify(user, "Abonelik pasif edildi", f"{plan} aboneliğiniz pasif edildi.", "warning", "⭐", "/membership/", dedupe_minutes=5)

    @staticmethod
    def invoice_paid(user, invoice):
        number = getattr(invoice, "invoice_number", "Fatura")
        amount = getattr(invoice, "total_amount", "")
        return NotificationHelper.notify(user, "Fatura ödendi", f"{number} numaralı fatura ödendi. Tutar: ₺{amount}", "success", "🧾", "/membership/", dedupe_minutes=5)

    @staticmethod
    def invoice_status_changed(user, invoice, old_status, new_status):
        number = getattr(invoice, "invoice_number", "Fatura")
        level = "success" if new_status == "paid" else "warning" if new_status in ["cancelled", "refunded"] else "info"
        return NotificationHelper.notify(user, "Fatura durumu değişti", f"{number}: {old_status} → {new_status}", level, "🧾", "/membership/", dedupe_minutes=5)

    @staticmethod
    def report_ready(user, report):
        name = getattr(report, "name", None) or getattr(report, "title", None) or "Rapor"
        return NotificationHelper.notify(user, "Rapor hazır", f"{name} raporunuz hazırlandı.", "success", "📄", "/reports/", dedupe_minutes=5)

    @staticmethod
    def budget_optimization_applied(user, log):
        new_budget = getattr(log, "new_budget", "")
        return NotificationHelper.notify(user, "Bütçe optimizasyonu uygulandı", f"Bir reklam bütçesi optimize edildi. Yeni bütçe: ₺{new_budget}", "success", "💰", object_activity_link(log) or "/budget-optimization/history/", dedupe_minutes=5)
