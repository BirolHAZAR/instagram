from django.urls import path

from core.views.health_center import health_center
from core.views.creative_center import creative_center
from core.views.performance_center import performance_center
from core.views.reports_center import reports_center
from core.views.campaign_center import campaign_center
from core.views.sync_center import sync_center


urlpatterns = [
    # Reklamlar
    path("reklam-paneli/", health_center, name="reklam_panel"),
    path("reklam-hareketleri/", health_center, name="reklam_hareketleri"),
    path("reklam-raporu/", reports_center, name="reklam_raporu"),

    # Rakip / competitor artık Ad(source_type=COMPETITOR)
    path("rakip-ekle/", health_center, name="rakip_ekle"),
    path("rakip-reklam-paneli/", health_center, name="rakip_reklam_paneli"),
    path("rakip-reklam-hareketleri/", health_center, name="rakip_reklam_hareketleri"),
    path("competitor-intelligence/", health_center, name="competitor_intelligence"),

    # AI / kreatif / performans
    path("ai-dashboard/", health_center, name="ai_dashboard"),
    path("creative-studio/", creative_center, name="creative_studio"),
    path("budget-optimization/", performance_center, name="budget_optimization"),
    path("anomaly-detector/", performance_center, name="anomaly_detector"),
    path("anomaly-dashboard/", performance_center, name="anomaly_dashboard"),

    # Yönetim menüsü
    path("optimizasyon-kurallari/", performance_center, name="optimizasyon_kurallari"),
    path("butce-optimizasyonu/uygula/", performance_center, name="apply_rules_to_campaigns"),
    path("optimizasyon-gecmisi/", performance_center, name="optimization_history"),

    # Liste sayfaları
    path("kampanyalar/", campaign_center, name="campaign_list"),
    path("raporlar/", reports_center, name="report_list"),

    # Footer / eski dashboard bağlantısı
    path("instagram-dashboard/", sync_center, name="instagram_dashboard"),
]
