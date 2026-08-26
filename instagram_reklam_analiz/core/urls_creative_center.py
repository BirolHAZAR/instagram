from django.urls import path
from core.views.creative_center import creative_center

urlpatterns = [
    path("creative-center/", creative_center, name="creative_center"),
]
