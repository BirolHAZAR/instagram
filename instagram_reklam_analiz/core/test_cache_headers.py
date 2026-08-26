from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from core.middleware.cache_headers import CacheControlMiddleware


class CacheControlMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = CacheControlMiddleware(lambda request: HttpResponse("ok"))

    def test_account_pages_cannot_be_cached_with_stale_csrf_tokens(self):
        response = self.middleware(self.factory.get("/accounts/login/"))

        self.assertEqual(
            response["Cache-Control"],
            "no-store, no-cache, must-revalidate, max-age=0, private",
        )
        self.assertEqual(response["Pragma"], "no-cache")
        self.assertEqual(response["Expires"], "0")
        self.assertIn("Cookie", response["Vary"])

    def test_api_cache_policy_is_unchanged(self):
        response = self.middleware(self.factory.get("/api/competitors/instagram/"))

        self.assertEqual(
            response["Cache-Control"],
            "no-store, no-cache, must-revalidate, max-age=0",
        )
