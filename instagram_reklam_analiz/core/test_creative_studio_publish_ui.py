from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class CreativeStudioPublishUiTests(SimpleTestCase):
    def test_publish_button_has_loading_and_error_feedback(self):
        template = (
            Path(settings.BASE_DIR)
            / "core"
            / "templates"
            / "creative_studio"
            / "dashboard.html"
        ).read_text(encoding="utf-8")

        self.assertIn('id="publishStatus"', template)
        self.assertIn("publishInProgress", template)
        self.assertIn("Gönderiliyor…", template)
        self.assertIn("Görsel platforma aktarılıyor", template)
        self.assertIn("setPublishing(false, error.message", template)
