from django.urls import path

from core.views.fihrist import fihrist


urlpatterns = [
    path("fihrist/", fihrist, name="fihrist"),
]
