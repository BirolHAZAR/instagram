from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import (
    AICreditLedger,
    AICreditPackage,
    Invoice,
    LegalAcceptance,
    MembershipPlan,
    Payment,
    PaymentTransaction,
    ProductResearchLedger,
    ProductResearchPackage,
    ReferralCode,
    ReferralProgramSetting,
    ReferralReward,
)
from core.services.bank_transfer_approval import approve_bank_transfer_payment


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class PurchaseFlowTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="buyer",
            email="buyer@example.com",
            password="Test12345!",
        )
        self.client.force_login(self.user)
        self.plan = MembershipPlan.objects.create(
            name="purchase-test",
            display_name="Test İşletme",
            plan_type=MembershipPlan.PLAN_TYPE_BUSINESS,
            price=Decimal("1000.00"),
            price_with_kdv=Decimal("1200.00"),
            features="Raporlama",
            is_active=True,
            ai_credits_per_month=100,
        )
        self.ai_package = AICreditPackage.objects.create(
            name="ai-test",
            display_name="1.000 AI Kredi",
            credits=1000,
            price=Decimal("100.00"),
            price_with_kdv=Decimal("120.00"),
            is_active=True,
        )
        self.research_package = ProductResearchPackage.objects.create(
            name="research-test",
            display_name="100 Ürün Araştırma",
            units=100,
            price=Decimal("200.00"),
            price_with_kdv=Decimal("240.00"),
            is_active=True,
        )

    def card_payload(self, **overrides):
        payload = {
            "customer_type": "individual",
            "first_name": "Test",
            "last_name": "Buyer",
            "email": self.user.email,
            "phone": "5551112233",
            "tc_kimlik": "11111111111",
            "company_name": "",
            "tax_office": "",
            "tax_number": "",
            "address": "Test Mahallesi 1",
            "city": "İstanbul",
            "district": "Kadıköy",
            "zip_code": "34000",
            "payment_method": "credit_card",
            "card_holder": "TEST BUYER",
            "card_number": "4242424242424242",
            "expiry_month": "12",
            "expiry_year": "99",
            "cvv": "123",
            "billing_period": "monthly",
            "legal_acceptance": "on",
            "immediate_service_consent": "on",
        }
        payload.update(overrides)
        return payload

    def bank_payload(self):
        return self.card_payload(
            payment_method="bank_transfer",
            card_holder="",
            card_number="",
            expiry_month="",
            expiry_year="",
            cvv="",
            transfer_sender_name="Test Buyer",
            transfer_bank_name="Test Bank",
            transfer_date="2026-07-16",
            transfer_receipt_reference="TEST-001",
        )

    def test_all_pricing_purchase_links_open_checkout(self):
        response = self.client.get(reverse("pricing"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("checkout", args=[self.plan.id]))
        self.assertContains(response, reverse("credit_checkout", args=[self.ai_package.id]))
        self.assertContains(response, reverse("product_research_checkout", args=[self.research_package.id]))

        for url in (
            reverse("checkout", args=[self.plan.id]),
            reverse("credit_checkout", args=[self.ai_package.id]),
            reverse("product_research_checkout", args=[self.research_package.id]),
        ):
            checkout_response = self.client.get(url)
            self.assertEqual(checkout_response.status_code, 200, url)
            self.assertContains(checkout_response, 'id="checkout-form"')

    def test_ai_credit_card_purchase_creates_complete_accounting_chain(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("credit_checkout", args=[self.ai_package.id]),
                self.card_payload(),
            )
        self.assertRedirects(response, reverse("payment_success"), fetch_redirect_response=False)
        payment = Payment.objects.get(ai_credit_package=self.ai_package, user=self.user)
        self.assertEqual(payment.status, "completed")
        self.assertEqual(payment.amount, Decimal("120.00"))
        self.assertTrue(PaymentTransaction.objects.filter(payment=payment, status="success").exists())
        self.assertTrue(Invoice.objects.filter(user=self.user, total_amount=payment.amount, is_paid=True).exists())
        self.assertTrue(AICreditLedger.objects.filter(user=self.user, package=self.ai_package, amount=1000).exists())
        acceptance = LegalAcceptance.objects.get(payment=payment)
        self.assertTrue(acceptance.immediate_service_consent)
        self.assertEqual(len(acceptance.document_snapshots), 5)
        self.assertTrue(all(snapshot["content_sha256"] for snapshot in acceptance.document_snapshots))
        self.assertEqual(len(mail.outbox), 1)
        pdf_attachments = [attachment for attachment in mail.outbox[0].attachments if attachment[2] == "application/pdf"]
        self.assertEqual(len(pdf_attachments), 5)
        acceptance.refresh_from_db()
        self.assertIsNotNone(acceptance.email_sent_at)

    def test_purchase_is_blocked_without_legal_consents(self):
        payload = self.card_payload()
        payload.pop("legal_acceptance")
        payload.pop("immediate_service_consent")
        response = self.client.post(reverse("credit_checkout", args=[self.ai_package.id]), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "satış ve üyelik sözleşmelerini onaylamalısınız")
        self.assertFalse(Payment.objects.filter(user=self.user).exists())

    def test_product_research_card_purchase_creates_complete_accounting_chain(self):
        response = self.client.post(
            reverse("product_research_checkout", args=[self.research_package.id]),
            self.card_payload(),
        )
        self.assertRedirects(response, reverse("payment_success"), fetch_redirect_response=False)
        payment = Payment.objects.get(product_research_package=self.research_package, user=self.user)
        self.assertEqual(payment.status, "completed")
        self.assertTrue(PaymentTransaction.objects.filter(payment=payment, status="success").exists())
        self.assertTrue(Invoice.objects.filter(user=self.user, total_amount=payment.amount, is_paid=True).exists())
        self.assertTrue(ProductResearchLedger.objects.filter(user=self.user, package=self.research_package, amount=100).exists())

    @patch("core.views.payment._send_bank_transfer_notice")
    def test_addon_bank_transfer_is_loaded_once_after_admin_approval(self, send_notice):
        response = self.client.post(
            reverse("credit_checkout", args=[self.ai_package.id]),
            self.bank_payload(),
        )
        self.assertRedirects(response, reverse("payment_success"), fetch_redirect_response=False)
        payment = Payment.objects.get(ai_credit_package=self.ai_package, user=self.user)
        self.assertEqual(payment.status, "pending")
        self.assertFalse(AICreditLedger.objects.filter(package=self.ai_package, action=AICreditLedger.ACTION_PURCHASE).exists())
        self.assertTrue(Invoice.objects.filter(user=self.user, is_paid=False, status="draft").exists())

        result = approve_bank_transfer_payment(payment, approved_by=self.user)
        self.assertTrue(result["approved"])
        payment.refresh_from_db()
        self.assertEqual(payment.status, "completed")
        self.assertEqual(AICreditLedger.objects.filter(reference=f"bank-ai-credit-package:{self.ai_package.id}:{payment.id}").count(), 1)
        self.assertTrue(Invoice.objects.filter(user=self.user, is_paid=True, status="paid").exists())

        second = approve_bank_transfer_payment(payment, approved_by=self.user)
        self.assertFalse(second["approved"])
        self.assertEqual(AICreditLedger.objects.filter(reference=f"bank-ai-credit-package:{self.ai_package.id}:{payment.id}").count(), 1)
        send_notice.assert_called_once()

    def test_referral_code_survives_pricing_and_discounts_first_subscription(self):
        User = get_user_model()
        referrer = User.objects.create_user(username="referrer", email="referrer@example.com", password="Test12345!")
        code = ReferralCode.objects.create(owner=referrer, code="PROMO10", reward_amount=500)
        settings = ReferralProgramSetting.current()
        settings.is_enabled = True
        settings.new_customer_discount_percent = Decimal("10.00")
        settings.default_reward_amount = 500
        settings.save()

        self.client.get(reverse("pricing"), {"ref": code.code})
        checkout = self.client.get(reverse("checkout", args=[self.plan.id]))
        self.assertContains(checkout, f'value="{code.code}"')

        response = self.client.post(
            reverse("checkout", args=[self.plan.id]),
            self.card_payload(referral_code=code.code),
        )
        self.assertRedirects(response, reverse("payment_success"), fetch_redirect_response=False)
        payment = Payment.objects.get(user=self.user, plan=self.plan)
        self.assertEqual(payment.amount, Decimal("1080.00"))
        reward = ReferralReward.objects.get(referral_code=code, referred_user=self.user)
        self.assertEqual(reward.status, ReferralReward.STATUS_AWARDED)
        self.assertTrue(AICreditLedger.objects.filter(user=referrer, reference=f"referral-reward:{reward.id}").exists())
