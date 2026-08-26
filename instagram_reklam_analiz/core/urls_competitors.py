# core/urls_competitors.py
from django.urls import path

from core.views.competitor_intelligence import competitor_intelligence
from core.views.demo_landing import demo_competitor_landing
from core.views.rakip_ekle import (
    api_rakip_detay,
    api_rakip_guncelle,
    api_rakip_sil,
    api_rakipler,
    rakip_ekle,
)
from core.views.rakip_reklam_hareketleri import (
    api_rakip_reklam_hareketleri,
    rakip_reklam_hareketleri,
)
from core.views.rakip_reklam_paneli import (
    api_rakip_reklam_sync,
    api_rakip_reklamlar,
    rakip_reklam_paneli,
)


urlpatterns = [
    path(
        "rakip/<slug:identifier>/kampanya-<int:campaign_no>",
        demo_competitor_landing,
        name="demo_competitor_landing",
    ),
    path("rakip/ekle/", rakip_ekle, name="rakip_ekle"),

    path("rakip-reklam-paneli/", rakip_reklam_paneli, name="rakip_reklam_paneli"),
    path("rakip-reklam-hareketleri/", rakip_reklam_hareketleri, name="rakip_reklam_hareketleri"),
    path("competitor-intelligence/", competitor_intelligence, name="competitor_intelligence"),

    path("api/rakipler/", api_rakipler, name="api_rakipler"),
    path("api/rakipler/<int:competitor_id>/detay/", api_rakip_detay, name="api_rakip_detay"),
    path("api/rakip-guncelle/<int:competitor_id>/", api_rakip_guncelle, name="api_rakip_guncelle"),
    path("api/rakip-sil/<int:competitor_id>/", api_rakip_sil, name="api_rakip_sil"),

    path("api/rakip-reklamlar/<int:competitor_id>/", api_rakip_reklamlar, name="api_rakip_reklamlar"),
    path("api/rakip-reklam-sync/<int:competitor_id>/", api_rakip_reklam_sync, name="api_rakip_reklam_sync"),
    path("api/rakip-reklam-hareketleri/", api_rakip_reklam_hareketleri, name="api_rakip_reklam_hareketleri"),
]
