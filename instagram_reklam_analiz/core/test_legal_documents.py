from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib import admin

from core.legal_defaults import LEGAL_DOCUMENTS
from core.models import LegalDocument, LegalSiteSettings


@override_settings(
    DEBUG_PROPAGATE_EXCEPTIONS=True,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class LegalDocumentTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="legal-admin",
            email="legal-admin@example.com",
            password="test-password",
            is_staff=True,
            is_superuser=True,
        )
        LegalDocument.objects.update(status=LegalDocument.STATUS_DRAFT, published_at=None)

    def test_all_default_documents_are_seeded_as_drafts(self):
        self.assertEqual(len(LEGAL_DOCUMENTS), 20)
        self.assertEqual(LegalDocument.objects.count(), 20)
        self.assertFalse(LegalDocument.objects.exclude(status=LegalDocument.STATUS_DRAFT).exists())

    def test_public_index_only_shows_published_documents(self):
        document = LegalDocument.objects.get(slug="gizlilik-politikasi")
        response = self.client.get(reverse("legal_document_index"))
        self.assertNotContains(response, document.title)

        document.publish(self.staff)
        response = self.client.get(reverse("legal_document_index"))
        self.assertContains(response, document.title)
        self.assertContains(response, document.get_absolute_url())

    def test_draft_detail_is_staff_preview_only(self):
        document = LegalDocument.objects.get(slug="kvkk-aydinlatma-metni")
        self.assertEqual(self.client.get(document.get_absolute_url()).status_code, 404)

        self.client.force_login(self.staff)
        response = self.client.get(document.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "yalnızca personel önizlemesinde")

    def test_company_tokens_are_rendered_without_leaking_placeholders(self):
        settings_obj = LegalSiteSettings.load()
        self.assertEqual(settings_obj.company_name, "HZR Yazılım Danışmanlık Dijital Paz. LTD ŞTİ")
        document = LegalDocument.objects.get(slug="mesafeli-satis-sozlesmesi")
        document.publish(self.staff)

        response = self.client.get(document.get_absolute_url())
        self.assertContains(response, settings_obj.company_name)
        self.assertContains(response, "info@reklamanaliz.net")
        self.assertNotContains(response, "[[COMPANY_NAME]]")

    def test_staff_can_preview_all_statuses_from_index(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("legal_document_index") + "?preview=1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Personel önizlemesi")
        self.assertContains(response, "Mesafeli Satış Sözleşmesi")

    def test_admin_pages_are_registered(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("admin:core_legaldocument_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:core_legalsitesettings_changelist")).status_code, 200)

    def test_admin_view_on_site_uses_relative_document_url(self):
        document = LegalDocument.objects.get(slug="mesafeli-satis-sozlesmesi")
        model_admin = admin.site._registry[LegalDocument]
        self.assertEqual(model_admin.get_view_on_site_url(document), document.get_absolute_url())
