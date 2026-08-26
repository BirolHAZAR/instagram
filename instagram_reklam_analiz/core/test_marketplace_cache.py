from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from core.services.web_market_research import search_market


@override_settings(SERPAPI_API_KEY="cache-test", TAVILY_API_KEY="")
class MarketplaceResearchCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch("core.services.web_market_research._serpapi_search")
    def test_identical_search_uses_cached_provider_result(self, provider):
        provider.return_value = [{
            "platform": "Test",
            "title": "Kadın pamuk şortlu takım",
            "seller": "Test",
            "price": "499.90",
            "currency": "TRY",
            "similarity": 90,
            "competition_level": "",
            "url": "https://example.com/product/1",
            "image_url": "",
            "snippet": "",
            "sold_count": 0,
            "data_provider": "serpapi_google_shopping",
            "price_source": "structured_extracted_price",
            "source_reliability": 0.95,
        }]

        first = search_market("kadın pamuk şortlu takım", max_results=20, include_tavily=False)
        second = search_market("kadın pamuk şortlu takım", max_results=20, include_tavily=False)

        self.assertEqual(first, second)
        self.assertEqual(provider.call_count, 1)
        self.assertIsNot(first, second)
