from abc import ABC, abstractmethod
from typing import Optional, Any
import logging
from django.utils import timezone
from core.models import PlatformAccount, SystemErrorLog

logger = logging.getLogger(__name__)

class BasePlatformAPI(ABC):
    """Tüm platform API'leri için temel sınıf"""
    
    def __init__(self, account: PlatformAccount):
        self.account = account
        self.platform = account.platform
    
    @abstractmethod
    def get_ads(self, since_days: int = 30) -> list:
        """
        Reklam listesini döndürür.
        Her reklam dict'i şu alanları içermelidir:
        - platform_ad_id: str (zorunlu)
        - name: str
        - title: str (opsiyonel)
        - description: str (opsiyonel)
        - media_type: str (image/video/carousel/reels)
        - media_url: str
        - thumbnail_url: str
        - status: str (active/paused/completed)
        - impressions: int
        - clicks: int
        - spend: float
        - ctr: float
        - ... diğer metrikler
        """
        pass
    
    def _handle_error(self, error: Exception, context: Optional[dict[Any, Any]] = None):
        """Hata yönetimi – loglama ve kayıt"""
        logger.error(f"[{self.platform}] {str(error)}", exc_info=True)
        SystemErrorLog.objects.create(
            severity='error',
            message=str(error),
            tags={'platform': self.platform, 'account_id': self.account.pk},
            extra_data=context or {},
            user=self.account.user,
        )
        # İsterseniz Sentry'e de gönderin
        # capture_exception(error)