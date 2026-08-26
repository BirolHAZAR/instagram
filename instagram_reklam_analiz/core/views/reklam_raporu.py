from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from core.models import Ad, PlatformAccount, Platform


@login_required
def reklam_raporu(request):
    reklamlar = Ad.objects.filter(user=request.user, source_type="OWN").select_related("platform_account", "platform_account__platform").order_by("-created_at")
    return render(request, "reklamlar/reklam_raporu.html", {"reklamlar": reklamlar, "v2_only": True})
