from django.urls import path
from core.views import campaigns

urlpatterns = [
    path('campaigns/', campaigns.campaign_list, name='campaign_list'),
    path('campaigns/create/', campaigns.campaign_create, name='campaign_create'),
    path('campaigns/<int:campaign_id>/', campaigns.campaign_detail, name='campaign_detail'),
    path('campaigns/<int:campaign_id>/edit/', campaigns.campaign_edit, name='campaign_edit'),
    path('campaigns/<int:campaign_id>/delete/', campaigns.campaign_delete, name='campaign_delete'),
    path('campaigns/<int:campaign_id>/pause/', campaigns.campaign_pause, name='campaign_pause'),
    path('campaigns/<int:campaign_id>/send-to-instagram/', campaigns.send_to_instagram, name='send_to_instagram'),
]
