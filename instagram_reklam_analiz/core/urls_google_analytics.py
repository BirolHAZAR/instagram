from django.urls import path

from core.views.google_analytics import (
    google_analytics_center,
    google_analytics_property_detail,
)


urlpatterns = [
    path("google-analytics/", google_analytics_center, name="google_analytics_center"),
    path("google-analytics/properties/<int:property_id>/", google_analytics_property_detail, name="google_analytics_property_detail"),
]
