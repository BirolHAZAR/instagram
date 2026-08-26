from django.urls import path
from core.views import main, dashboard_v2
from core.views.dashboard_v2 import executive_dashboard
urlpatterns = [
    path('', main.index, name='index'),
    path('about/', main.about, name='about'),
    path('contact/', main.contact, name='contact'),
    path('demo-talep/', main.demo_request, name='demo_request'),
    path('dashboard/', dashboard_v2.executive_dashboard, name='dashboard'),
    path('api/alerts/check/', dashboard_v2.check_alerts_api, name='check_alerts_api'),
    path('api/alerts/mark-read/', dashboard_v2.mark_alerts_read, name='mark_alerts_read'),
    path("executive-dashboard/", executive_dashboard, name="executive_dashboard"),
]
