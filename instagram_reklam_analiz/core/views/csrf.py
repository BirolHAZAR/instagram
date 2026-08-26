from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.views.csrf import csrf_failure as django_csrf_failure


def csrf_failure(request, reason=""):
    """Recover safely from a stale login form after an app/server restart."""
    if request.method == "POST" and request.path == reverse("account_login"):
        response = redirect(f"{reverse('account_login')}?csrf_refreshed=1")
        response.delete_cookie(
            settings.CSRF_COOKIE_NAME,
            path=settings.CSRF_COOKIE_PATH,
            domain=settings.CSRF_COOKIE_DOMAIN,
            samesite=settings.CSRF_COOKIE_SAMESITE,
        )
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
        return response

    return django_csrf_failure(request, reason=reason)
