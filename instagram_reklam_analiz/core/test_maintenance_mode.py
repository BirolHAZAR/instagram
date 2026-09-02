from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from core.middleware.maintenance_mode import MaintenanceModeMiddleware
from core.models import SiteMaintenance
from core.models.site_settings import MAINTENANCE_CACHE_KEY


class MaintenanceModeTests(TestCase):
    def setUp(self):
        cache.delete(MAINTENANCE_CACHE_KEY)
        self.factory = RequestFactory()
        self.middleware = MaintenanceModeMiddleware(lambda request: HttpResponse("normal"))

    def request(self, path):
        request = self.factory.get(path)
        request.user = AnonymousUser()
        return request

    def tearDown(self):
        cache.delete(MAINTENANCE_CACHE_KEY)

    def test_inactive_mode_allows_public_request(self):
        SiteMaintenance.objects.create(is_active=False)
        response = self.middleware(self.request("/dashboard/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"normal")

    def test_active_mode_serves_maintenance_page_with_503_headers(self):
        SiteMaintenance.objects.create(
            is_active=True,
            title="Planlı çalışma",
            message="Birazdan yeniden buradayız.",
            contact_email="destek@example.com",
        )
        response = self.middleware(self.request("/dashboard/"))
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "Planlı çalışma", status_code=503)
        self.assertContains(response, "destek@example.com", status_code=503)
        self.assertEqual(response["Retry-After"], "300")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_admin_and_infrastructure_paths_remain_available(self):
        SiteMaintenance.objects.create(is_active=True)
        for path in ("/admin/login/", "/static/app.css", "/media/logo.png", "/healthz/", "/favicon.ico"):
            with self.subTest(path=path):
                response = self.middleware(self.request(path))
                self.assertEqual(response.status_code, 200)

    def test_superuser_bypasses_maintenance_mode(self):
        SiteMaintenance.objects.create(is_active=True)
        user = get_user_model().objects.create_superuser(
            username="maintenance-admin",
            email="maintenance-admin@example.com",
            password="test-password",
        )
        request = self.factory.get("/admin/")
        request.user = user

        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"normal")

    def test_singleton_save_always_updates_the_same_record(self):
        first = SiteMaintenance.objects.create(is_active=False)
        second = SiteMaintenance(is_active=True, title="Yeni başlık")
        second.save()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SiteMaintenance.objects.count(), 1)
        self.assertTrue(SiteMaintenance.objects.get().is_active)

    def test_save_invalidates_cached_state(self):
        setting = SiteMaintenance.objects.create(is_active=False)
        self.middleware(self.request("/public/"))
        setting.is_active = True
        setting.save()
        response = self.middleware(self.request("/public/"))
        self.assertEqual(response.status_code, 503)
