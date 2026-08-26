from django.urls import path
from core.views import instagram

urlpatterns = [
    path('instagram/', instagram.instagram_dashboard, name='instagram_dashboard'),
    path('instagram/add/', instagram.add_instagram_account, name='add_instagram_account'),
    path('instagram/reklam-raporu/', instagram.instagram_reklam_raporu, name='instagram_reklam_raporu'),
    path('instagram/<int:account_id>/', instagram.instagram_account_detail, name='instagram_account_detail'),
    path('instagram/<int:account_id>/sync/', instagram.sync_instagram_data, name='sync_instagram_data'),
    path('instagram/<int:account_id>/delete/', instagram.delete_instagram_account, name='delete_instagram_account'),
    path('instagram/<int:account_id>/ads/', instagram.fetch_instagram_ads, name='fetch_instagram_ads'),
    path('instagram/<int:account_id>/fetch-ads/', instagram.fetch_instagram_ads, name='fetch_instagram_ads_alt'),
    path('instagram/<int:account_id>/stats/', instagram.get_instagram_stats, name='instagram_stats'),
]
