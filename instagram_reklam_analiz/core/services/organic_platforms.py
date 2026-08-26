from django.conf import settings


ORGANIC_PUBLISH_PLATFORMS = (
    {
        "code": "instagram",
        "name": "Instagram",
        "icon": "fab fa-instagram",
        "enabled_setting": "ORGANIC_INSTAGRAM_PUBLISH_ENABLED",
        "post_types": ("IMAGE", "CAROUSEL"),
        "capability": "Tek görsel veya 2–10 görsellik carousel",
        "integration_ready": True,
    },
    {
        "code": "facebook",
        "name": "Facebook",
        "icon": "fab fa-facebook",
        "enabled_setting": "ORGANIC_FACEBOOK_PUBLISH_ENABLED",
        "post_types": ("IMAGE",),
        "capability": "Sayfaya tek görsel gönderisi",
        "integration_ready": True,
    },
    {
        "code": "tiktok",
        "name": "TikTok",
        "icon": "fab fa-tiktok",
        "enabled_setting": "ORGANIC_TIKTOK_PUBLISH_ENABLED",
        "post_types": ("IMAGE", "VIDEO"),
        "capability": "Fotoğraf veya video gönderisi (video.publish onayı gerekir)",
        "integration_ready": True,
    },
    {
        "code": "x",
        "name": "X",
        "icon": "fab fa-x-twitter",
        "enabled_setting": "ORGANIC_X_PUBLISH_ENABLED",
        "post_types": ("TEXT",),
        "capability": "Metin gönderisi (tweet.write yetkisi gerekir)",
        "integration_ready": True,
    },
    {
        "code": "linkedin",
        "name": "LinkedIn",
        "icon": "fab fa-linkedin",
        "enabled_setting": "ORGANIC_LINKEDIN_PUBLISH_ENABLED",
        "post_types": ("TEXT",),
        "capability": "Üye veya şirket sayfası metin gönderisi (w_member_social/w_organization_social gerekir)",
        "integration_ready": True,
    },
)

ORGANIC_PUBLISH_PLATFORM_CODES = frozenset(
    platform["code"] for platform in ORGANIC_PUBLISH_PLATFORMS if platform["integration_ready"]
)


def get_organic_publish_platform(code):
    normalized_code = (code or "").strip().lower()
    return next(
        (platform for platform in ORGANIC_PUBLISH_PLATFORMS if platform["code"] == normalized_code),
        None,
    )


def is_organic_publish_enabled(code):
    platform = get_organic_publish_platform(code)
    return bool(platform and getattr(settings, platform["enabled_setting"], False))


def organic_publish_platform_rows():
    return [
        {
            **platform,
            "post_types": list(platform["post_types"]),
            "live_enabled": is_organic_publish_enabled(platform["code"]),
        }
        for platform in ORGANIC_PUBLISH_PLATFORMS
    ]
