from django.urls import path
from core.views.performance_center import performance_center

urlpatterns = [
    path("performance-center/", performance_center, name="performance_center"),
]
