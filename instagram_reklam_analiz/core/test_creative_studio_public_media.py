from django.test import SimpleTestCase, override_settings

from core.views.creative_studio import _public_media_url


class CreativeStudioPublicMediaUrlTests(SimpleTestCase):
    @override_settings(SITE_URL="https://reklamanaliz.net", PUBLIC_MEDIA_BASE_URL="")
    def test_relative_media_url_uses_public_site_url(self):
        self.assertEqual(
            _public_media_url("/media/creative_studio/33/20/variant-1.png"),
            "https://reklamanaliz.net/media/creative_studio/33/20/variant-1.png",
        )

    @override_settings(
        SITE_URL="https://reklamanaliz.net",
        PUBLIC_MEDIA_BASE_URL="https://cdn.reklamanaliz.net",
    )
    def test_explicit_public_media_base_has_priority(self):
        self.assertEqual(
            _public_media_url("/media/post.png"),
            "https://cdn.reklamanaliz.net/media/post.png",
        )

    def test_absolute_media_url_is_preserved(self):
        self.assertEqual(
            _public_media_url("https://cdn.example.com/post.png"),
            "https://cdn.example.com/post.png",
        )
