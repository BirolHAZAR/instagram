from types import SimpleNamespace

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from core.middleware.rate_limit import RateLimitMiddleware
from core.services.rate_limit import get_client_ip, parse_rate


class RateLimitTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def test_rate_parser(self):
        self.assertEqual(parse_rate("45/m"), (45, 60))
        self.assertEqual(parse_rate("5/300s"), (5, 300))

    @override_settings(RATE_LIMIT_TRUSTED_PROXIES=["127.0.0.1"])
    def test_forwarded_ip_is_only_used_for_trusted_proxy(self):
        trusted = self.factory.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.8")
        untrusted = self.factory.get("/", REMOTE_ADDR="198.51.100.4", HTTP_X_FORWARDED_FOR="203.0.113.8")
        self.assertEqual(get_client_ip(trusted), "203.0.113.8")
        self.assertEqual(get_client_ip(untrusted), "198.51.100.4")

    @override_settings(
        RATE_LIMIT_ENABLED=True,
        RATE_LIMIT_RULES=[
            {"name": "api", "path_prefixes": ["/api/"], "methods": ["POST"], "scope": "ip", "rate": "5/m"},
            {"name": "write", "path_prefixes": ["/api/"], "methods": ["POST"], "scope": "ip", "rate": "1/m"},
        ],
    )
    def test_all_matching_rules_are_enforced(self):
        middleware = RateLimitMiddleware(lambda request: HttpResponse("ok"))
        first = self.factory.post("/api/example/", REMOTE_ADDR="127.0.0.1")
        first.resolver_match = SimpleNamespace(url_name="example")
        self.assertIsNone(middleware.process_view(first, lambda: None, (), {}))
        second = self.factory.post("/api/example/", REMOTE_ADDR="127.0.0.1")
        second.resolver_match = SimpleNamespace(url_name="example")
        response = middleware.process_view(second, lambda: None, (), {})
        self.assertEqual(response.status_code, 429)
