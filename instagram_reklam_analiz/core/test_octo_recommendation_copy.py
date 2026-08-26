from types import SimpleNamespace

from django.test import SimpleTestCase

from core.services.octo_recommendation_engine import (
    _align_platform_references,
    _split_to_bullets,
    _without_repeated_finding,
)


class OctoRecommendationCopyTests(SimpleTestCase):
    def test_finding_title_is_not_repeated(self):
        title = "Gelir Verimi Düştü"
        items = [
            "Gelir Verimi Düştü: Harcanan paraya göre gelen gelir zayıfladı",
            "Kampanya: Bahar Kampanyası",
            "Tespit edilen durum: ROAS düşüşü",
        ]

        self.assertEqual(
            _without_repeated_finding(title, items),
            [title, "Kampanya: Bahar Kampanyası", "Tespit edilen durum: ROAS düşüşü"],
        )

    def test_ordinal_dot_does_not_split_campaign_name(self):
        items = _split_to_bullets("Kampanya: LinkedIn 1. Hesap Kampanya 2. Mevcut değer: 4.20")

        self.assertEqual(items[0], "Kampanya: LinkedIn 1. Hesap Kampanya 2")

    def test_wrong_platform_reference_is_aligned(self):
        task = SimpleNamespace(
            platform_account=SimpleNamespace(platform=SimpleNamespace(name="LinkedIn"))
        )

        text = _align_platform_references("YouTube reklamlarında teklif mesajı önemlidir", task)

        self.assertEqual(text, "LinkedIn reklamlarında teklif mesajı önemlidir")
