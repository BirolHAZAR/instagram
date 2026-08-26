from django.urls import path
from core.views.reports_center import reports_center

urlpatterns = [
    path("reports-center/", reports_center, name="reports_center"),
    path("reklam-raporu/", reports_center, name="reklam_raporu"),
    path("tum-reklam-raporu/", reports_center, name="tum_reklam_raporu"),
]