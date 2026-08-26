from django.urls import path

from core.views.platform_connections import platform_connections

urlpatterns = [
    path("platform-connections/", platform_connections, name="platform_connections"),
]