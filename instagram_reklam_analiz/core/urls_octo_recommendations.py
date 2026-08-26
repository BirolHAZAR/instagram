from django.urls import path

from core.views.octo_recommendations import campaign_octo_recommendations

urlpatterns = [
    path(
        "campaign-octo-recommendations/",
        campaign_octo_recommendations,
        name="campaign_octo_recommendations",
    ),
]
