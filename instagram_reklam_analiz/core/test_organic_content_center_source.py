from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse


class OrganicContentCenterSourceTests(SimpleTestCase):
    def test_center_only_lists_platform_synced_posts(self):
        source = (
            Path(settings.BASE_DIR) / "core" / "views" / "social_content.py"
        ).read_text(encoding="utf-8")
        self.assertIn('.filter(raw_data__source="instagram_media_sync")', source)
        self.assertIn('"source", "platform-sync-v1"', source)
        refresh_body = source.split(
            "def organic_content_refresh(request):", 1
        )[1].split("def organic_content_delete", 1)[0]
        self.assertNotIn("is_sync_due(", refresh_body)

    def test_synced_post_has_local_delete_action(self):
        self.assertEqual(
            reverse("organic_content_delete", args=[42]),
            "/organic-content/42/delete/",
        )
        template = (
            Path(settings.BASE_DIR)
            / "core"
            / "templates"
            / "social_content"
            / "organic_content_center.html"
        ).read_text(encoding="utf-8")
        self.assertIn("organic_content_delete", template)
        self.assertIn("Instagram gönderisi silinmeyecek", template)
