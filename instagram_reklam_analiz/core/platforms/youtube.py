from .base import BasePlatformAPI


class YouTubeAPI(BasePlatformAPI):
    def get_ads(self, since_days=30):
        return []
