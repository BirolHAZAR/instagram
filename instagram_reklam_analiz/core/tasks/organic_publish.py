from celery import shared_task

from core.models import SocialPost
from core.services.organic_publish import publish_post


@shared_task(name="core.tasks.organic_publish.publish_scheduled_social_post")
def publish_scheduled_social_post(post_id):
    post = SocialPost.objects.select_related(
        "platform_account__platform", "platform_connection__platform"
    ).filter(id=post_id, is_active=True).first()
    if not post:
        return {"success": False, "message": "Gönderi bulunamadı."}
    if post.posted_at:
        return {"success": True, "message": "Gönderi daha önce yayınlandı."}
    result = publish_post(post)
    return {"success": result.success, "message": result.message, "platform_post_id": result.platform_post_id}
