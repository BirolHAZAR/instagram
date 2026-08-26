from datetime import timedelta
from decimal import Decimal

from celery import shared_task
from django.utils import timezone


def update_job(job, progress, message=None, **counts):
    job.progress = progress

    if message:
        job.message = message

    for field, value in counts.items():
        if hasattr(job, field):
            setattr(job, field, value)

    job.save()


@shared_task(bind=True, max_retries=3)
def sync_platform_account_ads(self, job_id):
    from core.models import (
        PlatformSyncJob,
        PlatformAccount,
        Campaign,
        AdGroup,
        Creative,
        Ad,
        AdMetricHistory,
    )

    job = PlatformSyncJob.objects.select_related(
        "platform_account",
        "platform_account__platform",
        "platform_account__connection",
        "user",
    ).get(id=job_id)

    account = job.platform_account
    user = job.user

    try:
        job.status = "running"
        job.started_at = timezone.now()
        job.message = "Octo reklam hesabını inceliyor..."
        job.progress = 5
        job.save()

        connection = account.connection

        if not connection:
            raise Exception("Bu platform hesabına bağlı PlatformConnection bulunamadı.")

        if not connection.access_token:
            raise Exception("PlatformConnection access_token boş görünüyor.")

        start_date = timezone.now().date() - timedelta(days=job.days_back)
        end_date = timezone.now().date()

        update_job(job, 15, "Kampanyalar inceleniyor...")

        """
        BURASI GERÇEK API BAĞLANTI NOKTASI

        Sonraki adımda platforma göre şu fonksiyonları dolduracağız:

        Meta:
        - campaigns = fetch_meta_campaigns(connection, account, start_date, end_date)
        - adsets = fetch_meta_adsets(...)
        - ads = fetch_meta_ads(...)
        - insights = fetch_meta_insights(...)

        Şimdilik mevcut V2 verilerini okuyarak pipeline sonucunu güncelliyoruz.
        """

        campaigns_qs = Campaign.objects.filter(
            user=user,
            platform_account=account,
        )

        campaigns_count = campaigns_qs.count()

        update_job(
            job,
            30,
            "Reklam grupları inceleniyor...",
            campaigns_count=campaigns_count,
        )

        adgroups_qs = AdGroup.objects.filter(
            user=user,
            campaign__platform_account=account,
        )

        adgroups_count = adgroups_qs.count()

        update_job(
            job,
            45,
            "Reklamlar inceleniyor...",
            adgroups_count=adgroups_count,
        )

        ads_qs = Ad.objects.filter(
            user=user,
            platform_account=account,
            source_type="OWN",
        )

        ads_count = ads_qs.count()

        update_job(
            job,
            60,
            "Kreatifler analiz ediliyor...",
            ads_count=ads_count,
        )

        creatives_count = Creative.objects.filter(
            user=user,
            platform_account=account,
        ).count()

        update_job(
            job,
            75,
            "Geçmiş performans verileri inceleniyor...",
            creatives_count=creatives_count,
        )

        metrics_count = AdMetricHistory.objects.filter(
            ad__in=ads_qs,
            date__gte=start_date,
            date__lte=end_date,
        ).count()

        total_spend = AdMetricHistory.objects.filter(
            ad__in=ads_qs,
            date__gte=start_date,
            date__lte=end_date,
        ).values_list("spend", flat=True)

        total_spend_value = sum([x or Decimal("0") for x in total_spend])

        update_job(
            job,
            90,
            "Octo sonucu hazırlıyor...",
            metrics_count=metrics_count,
        )

        account.last_sync = timezone.now()
        account.save(update_fields=["last_sync"])

        job.status = "completed"
        job.progress = 100
        job.message = (
            f"{campaigns_count} kampanya, "
            f"{adgroups_count} reklam grubu, "
            f"{ads_count} reklam ve "
            f"{metrics_count} geçmiş metrik incelendi."
        )
        job.finished_at = timezone.now()
        job.result = {
            "campaigns_count": campaigns_count,
            "adgroups_count": adgroups_count,
            "ads_count": ads_count,
            "creatives_count": creatives_count,
            "metrics_count": metrics_count,
            "days_back": job.days_back,
            "total_spend": str(total_spend_value),
        }
        job.save()

        try:
            from core.tasks.admin_ops import generate_octo_tasks

            rule_task = generate_octo_tasks.apply_async(
                kwargs={
                    "user_id": user.id,
                    "account_id": account.id,
                    "trigger": "ad_sync",
                    "days": min(max(job.days_back, 7), 30),
                },
                countdown=5,
                queue="ai",
            )
            job.result["rule_engine"] = {"status": "queued", "task_id": rule_task.id}
        except Exception as exc:
            job.result["rule_engine"] = {
                "status": "periodic_fallback",
                "error": str(exc),
            }
        job.save(update_fields=["result", "updated_at"])

        return job.result

    except Exception as exc:
        job.status = "failed"
        job.progress = 100
        job.message = "Senkronizasyon sırasında hata oluştu."
        job.error_message = str(exc)
        job.finished_at = timezone.now()
        job.save()

        raise self.retry(exc=exc, countdown=60)
