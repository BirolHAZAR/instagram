from django.urls import path
from core.views import payment, platform_connect
from core.views.hesap_ekle import hesap_ekle_view, hesap_sil
from core.views import platform_connect

urlpatterns = [
    path(
        "platform-connections/",
        platform_connect.platform_connections,
        name="platform_connections"
    ),



    path('pricing/', payment.pricing_view, name='pricing'),
    path('checkout/<int:plan_id>/', payment.checkout, name='checkout'),
    path('checkout/ai-kredi/<int:package_id>/', payment.credit_checkout, name='credit_checkout'),
    path('checkout/urun-arastirma/<int:package_id>/', payment.product_research_checkout, name='product_research_checkout'),
    path('payment/success/', payment.payment_success, name='payment_success'),
    path('account/', payment.my_account, name='my_account'),
    path('account/subscriptions/', payment.my_subscriptions, name='my_subscriptions'),
    path('account/invoices/', payment.my_invoices, name='my_invoices'),
    path('account/payments/', payment.my_payments, name='my_payments'),
    path('account/invoices/<int:invoice_id>/pdf/', payment.invoice_pdf, name='invoice_pdf'),
    path('account/invoices/<int:invoice_id>/', payment.invoice_detail, name='invoice_detail'),
    path('hesap-ekle/', hesap_ekle_view, name='hesap_ekle'),
    path('hesap-sil/<int:account_id>/', hesap_sil, name='hesap_sil'),
    path('platform-connections/accounts/<int:account_id>/update/', platform_connect.platform_account_update, name='platform_account_update'),
    path('platform-connections/accounts/<int:account_id>/delete/', platform_connect.platform_account_delete, name='platform_account_delete'),
    path('connect/facebook/', platform_connect.facebook_login, name='facebook_login'),
    path('connect/facebook/callback/', platform_connect.facebook_callback, name='facebook_callback'),
]
