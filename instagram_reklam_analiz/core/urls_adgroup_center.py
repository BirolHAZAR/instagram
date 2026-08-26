from django.urls import path
from core.views.adgroup_center import adgroup_center

urlpatterns = [
    path("adgroup-center/", adgroup_center, name="adgroup_center"),
]
