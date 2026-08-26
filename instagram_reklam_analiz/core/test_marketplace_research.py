from decimal import Decimal
import base64
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from core.forms import MarketplaceProductResearchForm
from core.models import FeatureUsageLedger, MarketplaceProductResearch, UserProductResearchBalance
from core.services.marketplace_research import build_marketplace_research_result, refresh_tracked_research
from core.services.product_research_credits import current_cycle
from core.services.usage_metering import record_usage, record_usage_failure, usage_count
from core.services.web_market_research import (
    MarketResearchProviderError,
    _decimal_from_price,
    _representative_price,
    consolidate_market_items,
    enrich_market_items,
    extract_sales_signal,
    search_market,
)


User = get_user_model()


class MarketplacePriceExtractionTests(TestCase):
    def test_turkish_price_formats_are_parsed(self):
        self.assertEqual(_decimal_from_price("Sepette 1.299,90 TL"), Decimal("1299.90"))
        self.assertEqual(_decimal_from_price("₺ 749,5"), Decimal("749.50"))
        self.assertEqual(_decimal_from_price("TRY 2.499"), Decimal("2499.00"))

    def test_representative_price_uses_median_and_ignores_tiny_noise(self):
        text = "3 TL taksit 799,90 TL 899,90 TL 1.099,90 TL"
        self.assertEqual(_representative_price(text), Decimal("899.90"))

    def test_published_sales_signal_is_extracted(self):
        count, evidence = extract_sales_signal("Bu ürün geçen ay 1,2 bin+ kişi tarafından satın alındı.")
        self.assertEqual(count, 1200)
        self.assertIn("satın alındı", evidence)

    def test_results_are_deduplicated_and_outlier_is_removed(self):
        items = [
            {"title": "Pamuk gecelik A", "snippet": "", "price": "800", "url": "https://shop.test/a?ref=1"},
            {"title": "Pamuk gecelik A", "snippet": "", "price": "800", "url": "https://shop.test/a"},
            {"title": "Pamuk gecelik B", "snippet": "", "price": "900", "url": "https://other.test/b"},
            {"title": "Pamuk gecelik C", "snippet": "", "price": "1000", "url": "https://third.test/c"},
            {"title": "İlgisiz uç değer", "snippet": "", "price": "99999", "url": "https://noise.test/d"},
        ]
        result = consolidate_market_items(items, "pamuk gecelik", max_results=20)
        self.assertEqual(len(result), 3)
        self.assertNotIn("99999.00", [item["price"] for item in result])

    @override_settings(SERPAPI_API_KEY="serp-test", TAVILY_API_KEY="tavily-test")
    @patch("core.services.web_market_research._tavily_search")
    @patch("core.services.web_market_research._serpapi_search")
    def test_serpapi_and_tavily_run_together_and_structured_price_wins(self, serp_mock, tavily_mock):
        serp_mock.return_value = [{
            "title": "Pamuk gecelik",
            "price": "799.90",
            "url": "https://shop.test/product?source=shopping",
            "data_provider": "serpapi_google_shopping",
            "price_source": "structured_extracted_price",
            "source_reliability": 0.95,
        }]
        tavily_mock.return_value = [{
            "title": "Pamuk gecelik",
            "price": "999.90",
            "url": "https://shop.test/product",
            "data_provider": "tavily",
            "price_source": "page_content",
            "source_reliability": 0.65,
        }]
        result = search_market("pamuk gecelik", max_results=8)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["price"], "799.90")
        self.assertEqual(result[0]["data_provider"], "serpapi_google_shopping")
        serp_mock.assert_called_once()
        tavily_mock.assert_called_once()

    @override_settings(SERPAPI_API_KEY="serp-test", TAVILY_API_KEY="tavily-test")
    @patch("core.services.web_market_research._tavily_search")
    @patch("core.services.web_market_research._serpapi_search")
    def test_product_research_mode_uses_only_serpapi(self, serp_mock, tavily_mock):
        serp_mock.return_value = [{
            "title": "Pamuk gecelik",
            "price": "799.90",
            "url": "https://shop.test/product",
            "product_id": "123",
            "data_provider": "serpapi_google_shopping",
            "price_source": "structured_extracted_price",
            "source_reliability": 0.95,
        }]
        result = search_market("pamuk gecelik", max_results=8, include_tavily=False)
        self.assertEqual(result[0]["data_provider"], "serpapi_google_shopping")
        serp_mock.assert_called_once()
        tavily_mock.assert_not_called()

    def test_items_are_filtered_and_enriched(self):
        items = enrich_market_items(
            [
                {"title": "Siyah pamuk gecelik 899 TL", "snippet": "kadın pamuk", "price": "", "url": "https://a.test"},
                {"title": "Pamuk kadın gecelik", "snippet": "1.199,90 TL", "price": "", "url": "https://b.test"},
                {"title": "Fiyatsız sonuç", "snippet": "ürün açıklaması", "price": "", "url": "https://c.test"},
            ],
            "siyah pamuk kadın gecelik",
        )
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item["similarity"] >= 35 for item in items))
        self.assertTrue(all(item["competition_level"] for item in items))
        self.assertTrue(all(item["currency"] == "TRY" for item in items))


class MarketplaceResearchFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="research-form-user", password="test")

    def test_image_only_research_is_valid(self):
        image = SimpleUploadedFile(
            "product.png",
            base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="),
            content_type="image/png",
        )
        form = MarketplaceProductResearchForm(data={}, files={"product_image": image}, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_empty_research_is_rejected(self):
        form = MarketplaceProductResearchForm(data={}, user=self.user)
        self.assertFalse(form.is_valid())


class MarketplaceResearchPipelineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="research-pipeline-user", password="test")
        self.research = MarketplaceProductResearch.objects.create(
            user=self.user,
            title="Kadın gecelik",
            prompt="pamuk, siyah",
        )

    @patch("core.services.marketplace_research.search_market")
    @patch("core.services.marketplace_research.analyze_product_image")
    def test_vision_attributes_feed_live_research(self, vision_mock, search_mock):
        vision_mock.return_value = {
            "product_name": "Kadın gecelik",
            "category": "Giyim",
            "brand": "",
            "attributes": ["uzun kollu"],
            "search_terms": ["pamuk gecelik"],
        }
        search_mock.return_value = [
            {"title": "Ürün A", "price": "900.00", "currency": "TRY", "similarity": 85, "competition_level": "Orta rekabet", "url": "https://a.test/1", "platform": "a.test", "sold_count": 120},
            {"title": "Ürün B", "price": "1100.00", "currency": "TRY", "similarity": 78, "competition_level": "Düşük rekabet", "url": "https://b.test/2", "platform": "b.test", "sold_count": 0},
        ]
        result = build_marketplace_research_result(self.research)
        self.assertEqual(result["detected_category"], "Giyim")
        self.assertIn("uzun kollu", result["detected_attributes"])
        self.assertEqual(result["average_price"], Decimal("1000.00"))
        self.assertIn("pamuk gecelik", search_mock.call_args.args[0])
        self.assertEqual(result["raw_result"]["market_stats"]["active_model_count"], 2)
        self.assertEqual(result["raw_result"]["market_stats"]["published_sales_count"], 120)
        self.assertEqual(search_mock.call_count, 1)


class MarketplaceUsageRefundTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="research-refund-user", password="test")

    def test_failed_plan_usage_does_not_count_against_limit(self):
        ledger = record_usage(
            user=self.user,
            operation=FeatureUsageLedger.OP_MARKETPLACE_PRODUCT_RESEARCH,
            reference="test",
        )
        record_usage_failure(
            user=self.user,
            operation=FeatureUsageLedger.OP_MARKETPLACE_PRODUCT_RESEARCH,
            usage_ledger=ledger,
            reference="test:failed",
            note="provider failed",
        )
        ledger.refresh_from_db()
        self.assertEqual(ledger.status, FeatureUsageLedger.STATUS_FAILED)
        self.assertEqual(usage_count(self.user, FeatureUsageLedger.OP_MARKETPLACE_PRODUCT_RESEARCH), 0)

    def test_failed_purchased_usage_restores_extra_balance(self):
        cycle_start, cycle_end = current_cycle()
        balance = UserProductResearchBalance.objects.create(
            user=self.user,
            cycle_start=cycle_start,
            cycle_end=cycle_end,
            purchased_units=5,
            used_units=1,
            current_balance=4,
        )
        ledger = record_usage(
            user=self.user,
            operation=FeatureUsageLedger.OP_MARKETPLACE_PRODUCT_RESEARCH,
            reference="test-extra",
            metadata={"source": "purchased_product_research"},
        )
        record_usage_failure(
            user=self.user,
            operation=FeatureUsageLedger.OP_MARKETPLACE_PRODUCT_RESEARCH,
            usage_ledger=ledger,
            reference="test-extra:failed",
            note="provider failed",
        )
        balance.refresh_from_db()
        self.assertEqual(balance.used_units, 0)
        self.assertEqual(balance.current_balance, 5)


class MarketplacePriceTrackingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tracking-user", password="test")
        self.research = MarketplaceProductResearch.objects.create(
            user=self.user,
            title="Takip edilen ürün",
            prompt="pamuk",
            status=MarketplaceProductResearch.STATUS_COMPLETED,
            track_price=True,
            tracking_interval_hours=24,
            next_tracking_at=timezone.now(),
            raw_result={"market_stats": {}},
        )

    @patch("core.services.marketplace_research.record_usage_failure")
    @patch("core.services.marketplace_research.build_marketplace_research_result")
    @patch("core.services.marketplace_research.consume_usage")
    def test_temporary_provider_failure_keeps_tracking_active(
        self, consume_mock, build_mock, failure_mock,
    ):
        consume_mock.return_value = SimpleNamespace(allowed=True, ledger=SimpleNamespace())
        build_mock.side_effect = MarketResearchProviderError("temporary provider error")
        before = timezone.now()
        refresh_tracked_research(self.research)
        self.research.refresh_from_db()
        self.assertEqual(self.research.status, MarketplaceProductResearch.STATUS_COMPLETED)
        self.assertTrue(self.research.track_price)
        self.assertGreater(self.research.next_tracking_at, before)
        self.assertEqual(self.research.raw_result["tracking_last_error"], "temporary provider error")
        failure_mock.assert_called_once()

    @patch("core.services.marketplace_research.refresh_tracked_research")
    def test_single_tracking_task_loads_and_refreshes_product(self, refresh_mock):
        from core.tasks.marketplace_sync import refresh_single_tracked_research

        result = refresh_single_tracked_research.run(self.research.id)
        self.assertTrue(result["refreshed"])
        refresh_mock.assert_called_once()
