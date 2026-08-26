from __future__ import annotations

from dataclasses import dataclass
import requests

from django.conf import settings
from django.utils import timezone

from core.instagram_api import InstagramAPI
from core.models import SocialPost
from core.services.organic_platforms import get_organic_publish_platform, is_organic_publish_enabled


@dataclass
class PublishResult:
    success: bool
    message: str
    platform_post_id: str = ""


def _platform_code(post):
    platform = post.platform_account.platform if post.platform_account_id else post.platform_connection.platform if post.platform_connection_id else None
    return (getattr(platform, "code", "") or getattr(platform, "name", "") or "").lower()


def _token_for_post(post):
    return (post.platform_account.access_token if post.platform_account_id and post.platform_account.access_token else post.platform_connection.access_token if post.platform_connection_id else "")


def can_publish_post(post):
    code = _platform_code(post)
    platform = get_organic_publish_platform(code)
    if not platform or not platform["integration_ready"]:
        return False, "Bu platform için canlı yayın entegrasyonu desteklenmiyor."
    if not is_organic_publish_enabled(code):
        return False, f"{platform['name']} doğrudan yayınlama özelliği etkin değil."
    if not post.platform_account_id:
        return False, "Yayınlamak için bağlı platform hesabı seçilmeli."
    if not _token_for_post(post):
        return False, "Bağlı platform hesabında access token yok."
    if post.post_type not in {*platform["post_types"], "UNKNOWN"}:
        return False, f"{platform['name']} için {post.post_type} gönderi tipi desteklenmiyor."
    if post.post_type == "IMAGE" and not post.image_url:
        return False, "Canlı yayınlama için herkese açık görsel URL gerekli."
    if post.post_type == "CAROUSEL":
        carousel_images = (post.raw_data or {}).get("carousel_images") or []
        if not 2 <= len(carousel_images) <= 10:
            return False, "Carousel canlı yayını için 2–10 herkese açık görsel URL'si gerekli."
    return True, "Yayınlanabilir."


def _complete(post, post_id, payload, message):
    now = timezone.now()
    post.platform_post_id, post.posted_at = str(post_id), now
    post.raw_data = {**(post.raw_data or {}), "status": "published", "published_at": now.isoformat(), "publish_result": payload}
    post.save(update_fields=["platform_post_id", "posted_at", "raw_data", "updated_at"])
    return PublishResult(True, message, str(post_id))


def _fail(post, name, payload):
    error = payload.get("error") if isinstance(payload, dict) else payload
    post.raw_data = {**(post.raw_data or {}), "status": "failed", "publish_error": str(error or payload)[:500]}
    post.save(update_fields=["raw_data", "updated_at"])
    return PublishResult(False, f"{name} gönderisi yayınlanamadı: {error or payload}")


def publish_post(post):
    ok, reason = can_publish_post(post)
    if not ok:
        return PublishResult(False, reason)
    token, code = _token_for_post(post), _platform_code(post)
    try:
        if code == "facebook":
            response = requests.post(f"{settings.FACEBOOK_GRAPH_URL}/{post.platform_account.account_id}/photos", data={"url": post.image_url, "message": post.caption or "", "access_token": token}, timeout=45)
            payload = response.json(); post_id = payload.get("post_id") or payload.get("id")
            return _complete(post, post_id, payload, "Facebook gönderisi yayınlandı.") if response.ok and post_id else _fail(post, "Facebook", payload)
        if code == "instagram":
            account_id = (post.platform_account.extra_data or {}).get("instagram_business_account_id") or post.platform_account.account_id
            api = InstagramAPI(token)
            if post.post_type == "CAROUSEL":
                payload = api.publish_instagram_carousel(
                    account_id,
                    (post.raw_data or {}).get("carousel_images") or [],
                    post.caption or "",
                )
            else:
                payload = api.publish_instagram_post(account_id, post.image_url, post.caption or "")
            post_id = payload.get("id")
            return _complete(post, post_id, payload, "Instagram gönderisi yayınlandı.") if post_id else _fail(post, "Instagram", payload)
        if code == "tiktok":
            payload = {"post_info": {"title": (post.caption or "")[:2200], "privacy_level": (post.platform_account.extra_data or {}).get("privacy_level", "PUBLIC_TO_EVERYONE"), "disable_comment": False, "auto_add_music": True}, "source_info": {"source": "PULL_FROM_URL", "photo_cover_index": 0, "photo_images": [post.image_url]}, "post_mode": "DIRECT_POST", "media_type": "PHOTO"}
            response = requests.post("https://open.tiktokapis.com/v2/post/publish/content/init/", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}, json=payload, timeout=45)
            result = response.json(); post_id = (result.get("data") or {}).get("publish_id")
            return _complete(post, post_id, result, "TikTok gönderisi yayın işlemine alındı.") if response.ok and post_id else _fail(post, "TikTok", result)
        if code == "x":
            response = requests.post("https://api.x.com/2/tweets", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json={"text": (post.caption or "")[:280]}, timeout=45)
            payload = response.json(); post_id = (payload.get("data") or {}).get("id")
            return _complete(post, post_id, payload, "X gönderisi yayınlandı.") if response.ok and post_id else _fail(post, "X", payload)
        if code == "linkedin":
            extra = post.platform_account.extra_data or {}; author = extra.get("author_urn") or extra.get("organization_urn") or f"urn:li:person:{post.platform_account.account_id}"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "LinkedIn-Version": settings.LINKEDIN_API_VERSION, "X-Restli-Protocol-Version": "2.0.0"}
            body = {"author": author, "commentary": post.caption or "", "visibility": "PUBLIC", "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []}, "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
            response = requests.post("https://api.linkedin.com/rest/posts", headers=headers, json=body, timeout=45)
            payload = response.json() if response.content else {}; post_id = response.headers.get("x-restli-id") or payload.get("id")
            return _complete(post, post_id, payload, "LinkedIn gönderisi yayınlandı.") if response.ok and post_id else _fail(post, "LinkedIn", payload or {"status": response.status_code})
    except (requests.RequestException, ValueError) as exc:
        return _fail(post, get_organic_publish_platform(code)["name"], {"error": str(exc)})
    return PublishResult(False, "Yayın adaptörü bulunamadı.")
