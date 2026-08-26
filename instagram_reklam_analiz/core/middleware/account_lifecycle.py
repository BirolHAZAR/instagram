from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone


class PendingDeletionAccountMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            profile = getattr(user, "profile", None)
            suspends_at = getattr(profile, "deletion_suspends_at", None) if profile else None
            should_suspend = profile and profile.pending_deletion and (
                not suspends_at or suspends_at <= timezone.now()
            )
            if should_suspend:
                logout(request)
                messages.warning(
                    request,
                    "Hesabiniz silme bekleme surecinde. Devam etmek icin tekrar giris yapin.",
                )
                return redirect("account_login")

        return self.get_response(request)
