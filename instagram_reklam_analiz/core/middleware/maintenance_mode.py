from django.core.cache import cache
from django.db import OperationalError, ProgrammingError
from django.shortcuts import render

from core.models.site_settings import MAINTENANCE_CACHE_KEY, SiteMaintenance


class MaintenanceModeMiddleware:
    """Serve a 503 page for public requests while keeping administration usable."""

    CACHE_TIMEOUT = 10
    EXEMPT_PREFIXES = ("/admin/", "/static/", "/media/", "/health/", "/healthz/")
    EXEMPT_PATHS = ("/favicon.ico", "/robots.txt")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_exempt(request.path_info):
            return self.get_response(request)

        settings = self._get_settings()
        if settings and settings.is_active:
            response = render(
                request,
                "maintenance.html",
                {"maintenance": settings},
                status=503,
            )
            response["Retry-After"] = "300"
            response["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response["X-Robots-Tag"] = "noindex, nofollow"
            return response

        return self.get_response(request)

    @classmethod
    def _is_exempt(cls, path):
        return path in cls.EXEMPT_PATHS or any(path.startswith(prefix) for prefix in cls.EXEMPT_PREFIXES)

    @classmethod
    def _get_settings(cls):
        cached = cache.get(MAINTENANCE_CACHE_KEY)
        if cached is not None:
            return None if cached is False else cached
        try:
            settings = SiteMaintenance.objects.first()
        except (OperationalError, ProgrammingError):
            # Deploys must remain reachable while migrations are still being applied.
            return None
        cache.set(MAINTENANCE_CACHE_KEY, settings or False, cls.CACHE_TIMEOUT)
        return settings
