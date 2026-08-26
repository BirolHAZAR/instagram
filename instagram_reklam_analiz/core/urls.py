from django.urls import include, path
from core.views.language import set_language_preference
from core.views.octo_task_center import octo_task_center, octo_task_update


urlpatterns = [
    path('', include('core.urls_dashboard')),
    path('', include('core.urls_auth')),
    path('', include('core.urls_accounts')),
    path('', include('core.urls_agency')),
    path('', include('core.urls_campaigns')),
    path('', include('core.urls_instagram')),
    path('', include('core.urls_notifications')),
    path('', include('core.urls_fihrist')),
    path('', include('core.urls_legal')),
    path('', include('core.urls_api')),

    path('language/set/', set_language_preference, name='set_language_preference'),

    # V2 merkezler
    path('', include('core.urls_control_tower')),
    path('', include('core.urls_reports_center')),
    path('', include('core.urls_sync_center')),
    path('', include('core.urls_performance_center')),
    path('', include('core.urls_creative_center')),
    path('', include('core.urls_campaign_center')),
    path('', include('core.urls_campaign_panel')),
    path('', include('core.urls_octo_recommendations')),
    path('', include('core.urls_adgroup_center')),
    path('', include('core.urls_health_center')),

    # Eski sayfa URL isimleri korunuyor.
    # Bu sayfaların içindeki veritabanı bağlantıları yeni Ad / AdMetricHistory mimarisine çevrilecek.
    path('', include('core.urls_ads')),
    path('', include('core.urls_competitors')),
    path('', include('core.urls_reports')),
    path('', include('core.urls_ai')),
    path('', include('core.urls_creative')),
    path('', include('core.urls_budget')),
    path('', include('core.urls_anomaly')),
    path('', include('core.urls_competitor_intelligence')),
    path('', include('core.urls_social_content')),
    path('', include('core.urls_marketplace')),
    path('', include('core.urls_influencers')),
    path('', include('core.urls_google_analytics')),
    
    path("octo-gorev-merkezi/", octo_task_center, name="octo_task_center"),
    path("octo-gorev-merkezi/<int:task_id>/update/", octo_task_update, name="octo_task_update"),


]
