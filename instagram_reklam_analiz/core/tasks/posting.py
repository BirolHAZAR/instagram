# core/tasks/posting.py
import logging
from celery import shared_task
from django.utils import timezone

from core.models import InstagramPostQueue
from core.instagram_api import InstagramAPI

logger = logging.getLogger(__name__)


@shared_task(name="process_post_queue_task")
def process_post_queue_task():
    """Bekleyen gönderileri Instagram'da paylaşır."""
    pending_posts = InstagramPostQueue.objects.filter(
        status='pending',
        scheduled_at__lte=timezone.now()
    ) | InstagramPostQueue.objects.filter(status='pending', scheduled_at__isnull=True)

    for post in pending_posts:
        try:
            post.status = 'processing'
            post.save()

            api = InstagramAPI(post.instagram_account.access_token)
            result = api.publish_instagram_post(
                instagram_business_id=post.instagram_account.instagram_id,
                image_url=post.image_url,
                caption=post.caption
            )

            if 'id' in result:
                post.status = 'published'
                post.media_id = result['id']
                if hasattr(post, 'published_at'):
                    post.published_at = timezone.now()
            else:
                post.status = 'failed'
                post.error_message = str(result.get('error', 'Bilinmeyen API Hatası'))
            post.save()
        except Exception as e:
            post.status = 'failed'
            post.error_message = str(e)
            post.save()
            logger.error(f"Paylaşım Hatası (Queue ID: {post.id}): {str(e)}")