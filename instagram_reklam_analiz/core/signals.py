# core/signals.py
import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, logout as auth_logout
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone

from core.services.activity_service import object_activity_link
from core.services.account_lifecycle import reactivate_user_if_within_grace_period
from core.services.notification_events import notify_user
from core.services.referrals import cancel_referral_rewards_for_payment, ensure_user_referral_code
from core.services.trial import ensure_trial_subscription

logger = logging.getLogger(__name__)
User = get_user_model()


def _register_cache_invalidation_signals():
    from core.models import (
        ActivityLog, Ad, AdMetricHistory, BudgetOptimizationLog, Campaign,
        CampaignMetricHistory, Competitor, OctoTaskInstance, PlatformAccount,
        SocialPost, SocialPostMetricHistory,
    )
    from core.services.cache_invalidation import schedule_instance_cache_invalidation

    for model in (
        PlatformAccount, Campaign, Ad, AdMetricHistory, CampaignMetricHistory,
        Competitor, SocialPost, SocialPostMetricHistory, BudgetOptimizationLog,
        OctoTaskInstance, ActivityLog,
    ):
        post_save.connect(schedule_instance_cache_invalidation, sender=model, weak=False, dispatch_uid=f"cache_save_{model._meta.label_lower}")
        post_delete.connect(schedule_instance_cache_invalidation, sender=model, weak=False, dispatch_uid=f"cache_delete_{model._meta.label_lower}")


_register_cache_invalidation_signals()


@receiver(post_save, sender=User)
def create_trial_for_new_user(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        from core.models import UserProfile

        UserProfile.objects.get_or_create(user=instance)
    except Exception as exc:
        logger.warning("Kullanici profili olusturulamadi user_id=%s: %s", getattr(instance, "id", None), exc)
    try:
        ensure_trial_subscription(instance)
    except Exception as exc:
        logger.warning("Deneme aboneligi olusturulamadi user_id=%s: %s", getattr(instance, "id", None), exc)
    try:
        ensure_user_referral_code(instance)
    except Exception as exc:
        logger.warning("Referans kodu olusturulamadi user_id=%s: %s", getattr(instance, "id", None), exc)


@receiver(user_logged_in)
def reactivate_pending_deletion_account(sender, request, user, **kwargs):
    profile = getattr(user, "profile", None)
    if not profile or not profile.pending_deletion:
        return

    if profile.deletion_suspends_at and profile.deletion_suspends_at > timezone.now():
        messages.info(
            request,
            "Hesap silme talebiniz alindi; aktif aboneliginiz bittikten sonra aski sureci baslayacak.",
        )
        return

    if reactivate_user_if_within_grace_period(user):
        messages.success(request, "Hesabiniz askidan cikarildi. Silme talebiniz iptal edildi.")
        return

    auth_logout(request)
    messages.error(request, "Hesap silme bekleme sureniz doldugu icin bu hesap tekrar acilamaz.")


@receiver(user_logged_out)
def release_active_session(sender, request, user, **kwargs):
    if not user or not request:
        return
    session_key = request.session.session_key
    if not session_key:
        return
    from core.models import UserProfile

    UserProfile.objects.filter(
        user=user,
        active_session_key=session_key,
    ).update(active_session_key="", active_session_last_seen=None)


def _safe_name(obj, fallback="Kayıt"):
    return (
        getattr(obj, "name", None)
        or getattr(obj, "title", None)
        or getattr(obj, "headline", None)
        or fallback
    )


def _is_created(created):
    return bool(created)


# =========================================================
# COMPETITOR / RAKİP
# =========================================================

try:
    from core.models import Payment

    @receiver(post_save, sender=Payment)
    def cancel_referral_reward_when_payment_reversed(sender, instance, **kwargs):
        if getattr(instance, "status", "") not in {"failed", "refunded"}:
            return
        try:
            cancel_referral_rewards_for_payment(
                instance,
                note="Odeme basarisiz/iade durumuna alindigi icin referans odulu iptal edildi.",
            )
        except Exception as exc:
            logger.warning("Referans odulu iptal edilemedi payment_id=%s: %s", getattr(instance, "id", None), exc)

except Exception as exc:
    logger.debug("Payment referral signal yuklenemedi: %s", exc)


try:
    from core.models import Competitor

    @receiver(post_save, sender=Competitor)
    def notify_competitor_saved(sender, instance, created, **kwargs):
        if created:
            notify_user(
                user=instance.user,
                title="Yeni rakip eklendi",
                message=f"{_safe_name(instance, 'Rakip')} rakip listenize eklendi.",
                level="success",
                icon="🕵️",
                link=object_activity_link(instance) or "/rakip/ekle/",
                dedupe_key=f"competitor_created_{instance.id}",
            )
        else:
            notify_user(
                user=instance.user,
                title="Rakip bilgisi güncellendi",
                message=f"{_safe_name(instance, 'Rakip')} bilgileri güncellendi.",
                level="info",
                icon="✏️",
                link=object_activity_link(instance) or "/rakip/ekle/",
                dedupe_key=f"competitor_updated_{instance.id}",
            )

except Exception as exc:
    logger.debug("Competitor signal yüklenemedi: %s", exc)


# =========================================================
# AD / REKLAM
# =========================================================

try:
    from core.models import Ad

    @receiver(post_save, sender=Ad)
    def notify_ad_saved(sender, instance, created, **kwargs):
        if not created:
            return

        source_type = getattr(instance, "source_type", "") or ""
        name = _safe_name(instance, "Reklam")

        if source_type == "COMPETITOR":
            competitor_name = _safe_name(getattr(instance, "competitor", None), "rakip")
            notify_user(
                user=instance.user,
                title="Yeni rakip reklamı bulundu",
                message=f"{competitor_name} için yeni rakip reklamı kaydedildi: {name}",
                level="info",
                icon="👁️",
                link=object_activity_link(instance) or "/rakip-reklam-paneli/",
                dedupe_key=f"competitor_ad_created_{instance.id}",
            )
        elif source_type == "OWN":
            notify_user(
                user=instance.user,
                title="Yeni reklam kaydedildi",
                message=f"{name} reklam hesabınıza eklendi.",
                level="success",
                icon="📣",
                link=object_activity_link(instance) or "/reklam-hareketleri/",
                dedupe_key=f"own_ad_created_{instance.id}",
            )

except Exception as exc:
    logger.debug("Ad signal yüklenemedi: %s", exc)


# =========================================================
# AD METRIC HISTORY
# =========================================================

try:
    from core.models import AdMetricHistory

    @receiver(post_save, sender=AdMetricHistory)
    def notify_ad_metric_saved(sender, instance, created, **kwargs):
        if not created:
            return

        ad = getattr(instance, "ad", None)
        if not ad or not getattr(ad, "user", None):
            return

        ctr = float(getattr(instance, "ctr", 0) or 0)
        spend = float(getattr(instance, "spend", 0) or 0)
        engagement_rate = float(getattr(instance, "engagement_rate", 0) or 0)
        source_type = getattr(ad, "source_type", "")

        if ctr >= 5:
            notify_user(
                user=ad.user,
                title="Yüksek CTR tespit edildi",
                message=f"{_safe_name(ad, 'Reklam')} reklamında CTR %{ctr:.2f} seviyesine çıktı.",
                level="success",
                icon="🚀",
                link=object_activity_link(ad) or "/performance-center/",
                dedupe_key=f"admetric_high_ctr_{instance.id}",
            )

        if source_type == "COMPETITOR" and engagement_rate >= 5:
            notify_user(
                user=ad.user,
                title="Rakip reklamında yüksek etkileşim",
                message=f"{_safe_name(ad, 'Rakip reklam')} yüksek etkileşim oranı yakaladı: %{engagement_rate:.2f}",
                level="warning",
                icon="🔥",
                link=object_activity_link(ad) or "/rakip-reklam-hareketleri/",
                dedupe_key=f"competitor_metric_high_eng_{instance.id}",
            )

        if spend > 0 and ctr < 0.5:
            notify_user(
                user=ad.user,
                title="Düşük performans uyarısı",
                message=f"{_safe_name(ad, 'Reklam')} harcama yapıyor ancak CTR düşük: %{ctr:.2f}",
                level="warning",
                icon="⚠️",
                link=object_activity_link(ad) or "/performance-center/",
                dedupe_key=f"admetric_low_ctr_{instance.id}",
            )

except Exception as exc:
    logger.debug("AdMetricHistory signal yüklenemedi: %s", exc)


# =========================================================
# CREATIVE / CREATIVE METRIC HISTORY
# =========================================================

try:
    from core.models import CreativeMetricHistory

    @receiver(post_save, sender=CreativeMetricHistory)
    def notify_creative_metric_saved(sender, instance, created, **kwargs):
        if not created:
            return

        creative = getattr(instance, "creative", None)
        if not creative or not getattr(creative, "user", None):
            return

        engagement_rate = float(getattr(instance, "engagement_rate", 0) or 0)

        if engagement_rate >= 6:
            notify_user(
                user=creative.user,
                title="Güçlü kreatif tespit edildi",
                message=f"{_safe_name(creative, 'Kreatif')} yüksek etkileşim oranı aldı: %{engagement_rate:.2f}",
                level="success",
                icon="🎨",
                link=object_activity_link(creative) or "/creative-center/",
                dedupe_key=f"creative_high_eng_{instance.id}",
            )

except Exception as exc:
    logger.debug("CreativeMetricHistory signal yüklenemedi: %s", exc)


try:
    from core.models import CreativeProject

    @receiver(post_save, sender=CreativeProject)
    def notify_creative_project_saved(sender, instance, created, **kwargs):
        user = getattr(instance, "user", None)
        if not user:
            return

        status = (getattr(instance, "status", "") or "").lower()
        if created:
            notify_user(
                user=user,
                title="Yeni kreatif projesi oluşturuldu",
                message=f"{_safe_name(instance, 'Kreatif projesi')} oluşturuldu.",
                level="info",
                icon="🎬",
                link=object_activity_link(instance) or "/creative-center/",
                dedupe_key=f"creative_project_created_{instance.id}",
            )
        elif status in {"completed", "done", "ready"}:
            notify_user(
                user=user,
                title="Kreatif çalışma tamamlandı",
                message=f"{_safe_name(instance, 'Kreatif projesi')} tamamlandı.",
                level="success",
                icon="✅",
                link=object_activity_link(instance) or "/creative-center/",
                dedupe_key=f"creative_project_completed_{instance.id}",
            )

except Exception as exc:
    logger.debug("CreativeProject signal yüklenemedi: %s", exc)


# =========================================================
# PLATFORM SYNC JOB
# =========================================================

try:
    from core.models import PlatformSyncJob

    @receiver(post_save, sender=PlatformSyncJob)
    def notify_platform_sync_job_saved(sender, instance, created, **kwargs):
        user = getattr(instance, "user", None)
        if not user:
            account = getattr(instance, "platform_account", None)
            user = getattr(account, "user", None)

        if not user:
            return

        status = (getattr(instance, "status", "") or "").upper()

        if created:
            notify_user(
                user=user,
                title="Senkronizasyon başladı",
                message="Platform verileri senkronize edilmeye başladı.",
                level="info",
                icon="🔄",
                link=object_activity_link(instance) or "/sync-center/",
                dedupe_key=f"sync_job_created_{instance.id}",
            )
        elif status in {"SUCCESS", "COMPLETED", "DONE"}:
            notify_user(
                user=user,
                title="Senkronizasyon tamamlandı",
                message="Platform verileri başarıyla güncellendi.",
                level="success",
                icon="✅",
                link=object_activity_link(instance) or "/sync-center/",
                dedupe_key=f"sync_job_success_{instance.id}",
            )
        elif status in {"FAILED", "ERROR"}:
            notify_user(
                user=user,
                title="Senkronizasyon hatası",
                message=getattr(instance, "error_message", None) or "Platform senkronizasyonunda hata oluştu.",
                level="error",
                icon="❌",
                link=object_activity_link(instance) or "/sync-center/",
                dedupe_key=f"sync_job_failed_{instance.id}",
            )

except Exception as exc:
    logger.debug("PlatformSyncJob signal yüklenemedi: %s", exc)


# =========================================================
# RAW DATA SNAPSHOT
# =========================================================

try:
    from core.models import RawDataSnapshot

    @receiver(post_save, sender=RawDataSnapshot)
    def notify_raw_snapshot_saved(sender, instance, created, **kwargs):
        if not created:
            return

        user = getattr(instance, "user", None)
        if not user:
            return

        status = (getattr(instance, "status", "") or "").upper()

        if status == "FAILED":
            notify_user(
                user=user,
                title="API ham veri hatası",
                message=getattr(instance, "error_message", None) or "Ham veri çekimi sırasında hata oluştu.",
                level="error",
                icon="🧩",
                link=object_activity_link(instance) or "/sync-center/",
                dedupe_key=f"raw_snapshot_failed_{instance.id}",
            )

except Exception as exc:
    logger.debug("RawDataSnapshot signal yüklenemedi: %s", exc)


# =========================================================
# ANOMALY ALERT
# =========================================================

try:
    from core.models import AnomalyAlert

    @receiver(post_save, sender=AnomalyAlert)
    def notify_anomaly_alert_saved(sender, instance, created, **kwargs):
        if not created:
            return

        user = getattr(instance, "user", None)
        if not user:
            return

        severity = (getattr(instance, "severity", "") or "").lower()
        level = "warning"
        icon = "⚠️"

        if severity in {"critical", "high"}:
            level = "error"
            icon = "🚨"

        notify_user(
            user=user,
            title=getattr(instance, "title", None) or "Anomali tespit edildi",
            message=getattr(instance, "message", None) or "Reklam performansında olağan dışı hareket tespit edildi.",
            level=level,
            icon=icon,
            link=object_activity_link(instance) or "/anomaly-dashboard/",
            dedupe_key=f"anomaly_created_{instance.id}",
        )

except Exception as exc:
    logger.debug("AnomalyAlert signal yüklenemedi: %s", exc)


# =========================================================
# BUDGET OPTIMIZATION
# =========================================================

try:
    from core.models import BudgetOptimizationLog

    @receiver(post_save, sender=BudgetOptimizationLog)
    def notify_budget_log_saved(sender, instance, created, **kwargs):
        if not created:
            return

        user = getattr(instance, "user", None)
        if not user:
            return

        notify_user(
            user=user,
            title="Bütçe optimizasyonu uygulandı",
            message=getattr(instance, "message", None) or "Bir bütçe optimizasyon kaydı oluşturuldu.",
            level="success",
            icon="💰",
            link=object_activity_link(instance) or "/budget-optimization/",
            dedupe_key=f"budget_log_created_{instance.id}",
        )

except Exception as exc:
    logger.debug("BudgetOptimizationLog signal yüklenemedi: %s", exc)

# =========================================================
# NOTIFICATION REALTIME BROADCAST
# =========================================================
try:
    from core.models import MarketplaceSyncRun

    @receiver(post_save, sender=MarketplaceSyncRun)
    def notify_marketplace_sync_finished(sender, instance, created, **kwargs):
        if created or instance.status not in {"success", "failed", "skipped"}:
            return
        account = instance.marketplace_account
        if instance.status == "success":
            level, icon, title = "success", "fa-arrows-rotate", "Pazaryeri senkronizasyonu tamamlandı"
            message = f"{account.store_name}: {instance.fetched_count} ürün okundu, {instance.created_count} eklendi, {instance.updated_count} güncellendi."
        else:
            level, icon, title = "warning", "fa-triangle-exclamation", "Pazaryeri senkronizasyonu tamamlanamadı"
            message = f"{account.store_name}: {instance.error_message or 'Senkronizasyon sırasında hata oluştu.'}"
        notify_user(
            user=account.user, title=title, message=message[:500], level=level, icon=icon,
            link="/pazaryeri/urun-yonetimi/", dedupe_key=f"marketplace_sync_{instance.id}_{instance.status}",
        )

except Exception as exc:
    logger.debug("MarketplaceSyncRun bildirim sinyali yüklenemedi: %s", exc)


try:
    from django.db import transaction
    from core.models import Notification
    from core.services.activity_service import record_activity_from_notification
    from core.services.notification_preferences import send_notification_email
    from core.services.realtime_notifications import send_realtime_notification

    @receiver(post_save, sender=Notification)
    def broadcast_notification_created(sender, instance, created, **kwargs):
        if not created:
            return
        transaction.on_commit(lambda: record_activity_from_notification(instance))
        transaction.on_commit(lambda: send_realtime_notification(instance))
        transaction.on_commit(lambda: send_notification_email(instance))

except Exception as exc:
    logger.debug("Notification realtime signal yüklenemedi: %s", exc)
