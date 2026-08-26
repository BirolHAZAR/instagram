from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone

from core.models import UserProfile


class ConcurrentSessionMiddleware:
    """Limit normal users to one recently active browser session."""

    STALE_AFTER = timedelta(minutes=15)
    HEARTBEAT_AFTER = timedelta(minutes=1)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            not user
            or not user.is_authenticated
            or user.is_staff
            or user.is_superuser
            or user.get_username().strip().casefold() == "demo"
        ):
            return self.get_response(request)

        if not request.session.session_key:
            request.session.save()
        session_key = request.session.session_key
        now = timezone.now()

        with transaction.atomic():
            profile, _ = UserProfile.objects.select_for_update().get_or_create(user=user)
            if profile.allow_concurrent_sessions:
                return self.get_response(request)

            active_is_recent = (
                profile.active_session_key
                and profile.active_session_last_seen
                and profile.active_session_last_seen >= now - self.STALE_AFTER
            )
            if active_is_recent and profile.active_session_key != session_key:
                logout(request)
                messages.error(
                    request,
                    "Bu hesap başka bir tarayıcıda aktif. Devam etmek için diğer oturumdan çıkış yapın.",
                )
                return redirect("account_login")

            should_refresh = (
                profile.active_session_key != session_key
                or not profile.active_session_last_seen
                or profile.active_session_last_seen < now - self.HEARTBEAT_AFTER
            )
            if should_refresh:
                profile.active_session_key = session_key
                profile.active_session_last_seen = now
                profile.save(update_fields=["active_session_key", "active_session_last_seen", "updated_at"])

        return self.get_response(request)
