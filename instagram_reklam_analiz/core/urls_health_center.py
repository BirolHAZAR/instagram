from django.urls import path
from core.views.ad_health_report_card import ad_health_report_card
from core.views.health_center import health_center

urlpatterns = [
    path('reklam-saglik-karnesi/', ad_health_report_card, name='ad_health_report_card'),
    path('reklam-saglik-merkezi/', health_center, name='health_center'),
]
