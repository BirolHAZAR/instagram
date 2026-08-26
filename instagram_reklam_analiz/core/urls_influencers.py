from django.urls import path

from core.views.influencers import influencer_add, influencer_detail, influencer_discovery


urlpatterns = [
    path("influencers/", influencer_discovery, name="influencer_discovery"),
    path("influencers/add/", influencer_add, name="influencer_add"),
    path("influencers/<int:influencer_id>/", influencer_detail, name="influencer_detail"),
]
