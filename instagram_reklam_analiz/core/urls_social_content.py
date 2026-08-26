from django.urls import path

from core.views.social_content import (
    organic_content_center,
    organic_content_delete,
    organic_content_composer,
    organic_connections,
    organic_content_publish,
    organic_content_refresh,
    organic_content_sync_account,
)

urlpatterns = [
    path('organic-content/', organic_content_center, name='organic_content_center'),
    path('organic-content/compose/', organic_content_composer, name='organic_content_composer'),
    path('organic-content/connections/', organic_connections, name='organic_connections'),
    path('organic-content/refresh/', organic_content_refresh, name='organic_content_refresh'),
    path('organic-content/accounts/<int:account_id>/sync/', organic_content_sync_account, name='organic_content_sync_account'),
    path('organic-content/<int:post_id>/publish/', organic_content_publish, name='organic_content_publish'),
    path('organic-content/<int:post_id>/delete/', organic_content_delete, name='organic_content_delete'),
]
