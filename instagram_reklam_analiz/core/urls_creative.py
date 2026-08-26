from django.urls import path
from core.views import creative_studio

urlpatterns = [
    path('creative-studio/', creative_studio.creative_studio, name='creative_studio'),
    path('api/creative/generate/', creative_studio.generate_content_api, name='generate_content_api'),
    path('api/creative/reference-prompt/', creative_studio.generate_reference_prompt_api, name='creative_reference_prompt'),
    path('api/creative/publish/', creative_studio.publish_to_instagram_queue, name='creative_publish'),
    path('api/creative/templates/', creative_studio.get_saved_templates_api, name='creative_templates'),
    path('api/creative/project/<int:project_id>/', creative_studio.get_project_detail_api, name='creative_project_detail'),
    path('api/creative/project/<int:project_id>/variant/<int:variant_number>/text/', creative_studio.update_variant_text_api, name='creative_update_variant_text'),
    path('api/creative/project/<int:project_id>/variant/<int:variant_number>/regenerate-media/', creative_studio.regenerate_variant_media_api, name='creative_regenerate_media'),
    path('api/competitors/<str:platform_code>/', creative_studio.get_competitors_api, name='creative_competitors_by_platform'),
    path('api/competitor/<str:competitor_id>/ads/', creative_studio.get_competitor_ads_api, name='creative_competitor_ads'),
]
