from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect

from core.services.entitlements import get_access_subscription


class SubscriptionAccessMiddleware:
    """Require an active trial or paid subscription for authenticated app access."""

    DEFAULT_ALLOWED_PREFIXES = (
        "/static/",
        "/media/",
        "/admin/",
        "/accounts/",
        "/login/",
        "/signup/",
        "/logout/",
        "/pricing/",
        "/checkout/",
        "/payment/",
        "/i18n/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not getattr(settings, "SUBSCRIPTION_ACCESS_ENFORCED", True):
            return None

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or user.is_staff or user.is_superuser:
            return None

        path = request.path or "/"
        allowed_prefixes = tuple(
            getattr(settings, "SUBSCRIPTION_ACCESS_ALLOWED_PREFIXES", self.DEFAULT_ALLOWED_PREFIXES)
        )
        if path == "/" or path.startswith(allowed_prefixes):
            return None

        if get_access_subscription(user):
            return None

        if path.startswith("/api/") or "application/json" in request.headers.get("Accept", ""):
            return JsonResponse(
                {
                    "success": False,
                    "error": "subscription_required",
                    "message": "Ucretsiz deneme sureniz sona erdi. Devam etmek icin paket secmelisiniz.",
                },
                status=402,
            )
        return redirect("pricing")
