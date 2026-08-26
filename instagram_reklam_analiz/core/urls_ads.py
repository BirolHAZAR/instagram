from django.urls import path

from core.views.ads_panel import (
    ads_panel,
    api_ads_by_account,
    api_ad_detail,
    api_ad_rule_scan,
    api_ad_ai_report,
    api_platform_accounts,
    api_sync_account,
    api_sync_job_status,
)
from core.views.ads_center import ads_center

urlpatterns = [
    path("reklam-paneli/", ads_panel, name="reklam_panel"),

    path("ads-center/", ads_center, name="ads_center"),
    path("reklam-hareketleri/", ads_center, name="reklam_hareketleri"),

    path("api/platform-accounts/", api_platform_accounts, name="api_platform_accounts"),
    path("api/reklamlar/", api_ads_by_account, name="api_ads_by_account"),
    path("api/reklamlar/<int:ad_id>/detail/", api_ad_detail, name="api_ad_detail"),
    path("api/reklamlar/<int:ad_id>/rule-scan/", api_ad_rule_scan, name="api_ad_rule_scan"),
    path("api/reklamlar/<int:ad_id>/ai/<str:report_type>/", api_ad_ai_report, name="api_ad_ai_report"),

    path("api/sync-account/<int:account_id>/", api_sync_account, name="api_sync_account"),
    path("api/sync-job/<int:job_id>/", api_sync_job_status, name="api_sync_job_status"),

]
