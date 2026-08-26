from django.urls import path

from core.views.marketplace import (
    marketplace_accounts,
    marketplace_account_delete,
    marketplace_account_edit,
    marketplace_account_test,
    marketplace_price_history_report,
    marketplace_price_tracking,
    marketplace_product_management,
    marketplace_product_research,
    marketplace_product_research_status,
)


urlpatterns = [
    path("pazaryeri/urun-yonetimi/", marketplace_product_management, name="marketplace_product_management"),
    path("pazaryeri/urun-arastirma/", marketplace_product_research, name="marketplace_product_research"),
    path("pazaryeri/urun-arastirma/<int:research_id>/durum/", marketplace_product_research_status, name="marketplace_product_research_status"),
    path("pazaryeri/fiyat-takibi/", marketplace_price_tracking, name="marketplace_price_tracking"),
    path("pazaryeri/fiyat-gecmisi/", marketplace_price_history_report, name="marketplace_price_history_report"),
    path("pazaryeri/hesaplar/", marketplace_accounts, name="marketplace_accounts"),
    path("pazaryeri/hesaplar/<int:account_id>/duzenle/", marketplace_account_edit, name="marketplace_account_edit"),
    path("pazaryeri/hesaplar/<int:account_id>/test/", marketplace_account_test, name="marketplace_account_test"),
    path("pazaryeri/hesaplar/<int:account_id>/sil/", marketplace_account_delete, name="marketplace_account_delete"),
]
