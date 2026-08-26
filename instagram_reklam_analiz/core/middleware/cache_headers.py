from django.utils.deprecation import MiddlewareMixin
from django.utils.cache import patch_vary_headers


class CacheControlMiddleware(MiddlewareMixin):
    """Set cache headers for sensitive and static routes."""

    def process_response(self, request, response):
        path = request.path or ""

        # Authentication forms contain a CSRF token tied to the current cookie.
        # Never let browsers, proxies, or the back/forward cache reuse an old
        # form after Django has rotated that cookie during login/logout.
        if path.startswith(("/accounts/", "/login/", "/signup/", "/logout/")):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
            patch_vary_headers(response, ("Cookie",))
            return response

        if path.startswith("/admin/"):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
            response["Referrer-Policy"] = "same-origin"
            response["X-Content-Type-Options"] = "nosniff"
            return response

        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not path.startswith(("/static/", "/media/")):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
            patch_vary_headers(response, ("Cookie",))
            return response

        if path.startswith("/dashboard/"):
            response["Cache-Control"] = "private, max-age=300"
        elif path.startswith("/api/"):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        elif path.startswith("/static/"):
            response["Cache-Control"] = "public, max-age=86400"

        return response
