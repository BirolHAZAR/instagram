from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from core.models import UserProfile


@require_POST
def set_language_preference(request):
    language = "tr"

    if request.user.is_authenticated:
        profile, _created = UserProfile.objects.get_or_create(user=request.user)
        profile.preferred_language = language
        profile.save(update_fields=["preferred_language"])

    request.session["preferred_language"] = language

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "/"
    return redirect(next_url)
