from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from core.models import PlatformAccount, Ad, Platform


@login_required
def get_reklamlar(request):
    account_id = request.GET.get("account_id")
    qs = Ad.objects.filter(user=request.user, source_type="OWN").select_related("platform_account", "platform_account__platform")
    if account_id:
        qs = qs.filter(platform_account_id=account_id)
    return JsonResponse({"success": True, "reklamlar": [{"id": ad.id, "name": str(ad), "status": ad.status, "platform": ad.platform_account.platform.code if ad.platform_account else ""} for ad in qs[:200]]})
