# core/tasks/platform_tasks.py
"""Platform senkronizasyon task köprüsü.

Eski task path'leri korur, gerçek işi V2 platform sync sistemine devreder.
"""
from celery import shared_task

from core.tasks.v2_platform_sync import sync_v2_platform_account_ads, sync_all_v2_platform_accounts


@shared_task(name="core.tasks.platform_tasks.sync_all_platform_accounts")
def sync_all_platform_accounts():
    return sync_all_v2_platform_accounts()


# Geriye uyumluluk alias'ları
sync_facebook_ads = sync_v2_platform_account_ads
sync_tiktok_ads = sync_v2_platform_account_ads
sync_google_ads = sync_v2_platform_account_ads
sync_linkedin_ads = sync_v2_platform_account_ads
sync_x_ads = sync_v2_platform_account_ads
sync_youtube_ads = sync_v2_platform_account_ads
sync_instagram_ads = sync_v2_platform_account_ads
