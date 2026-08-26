from django.urls import path
from core.views.sync_center import sync_center

urlpatterns = [
    path("sync-center/", sync_center, name="sync_center"),
]
