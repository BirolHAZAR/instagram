from core.models import Ad, AdMetricHistory


class TimelineService:
    def __init__(self, user):
        self.user = user

    def reklam_timeline(self, reklam_id):
        ad = Ad.objects.get(id=reklam_id, user=self.user)
        history = AdMetricHistory.objects.filter(ad=ad).order_by("date")
        return {"ad": ad, "history": history}

    def rakip_reklam_timeline(self, rakip_reklam_id):
        ad = Ad.objects.get(id=rakip_reklam_id, user=self.user, source_type="COMPETITOR")
        history = AdMetricHistory.objects.filter(ad=ad).order_by("date")
        return {"ad": ad, "history": history}
