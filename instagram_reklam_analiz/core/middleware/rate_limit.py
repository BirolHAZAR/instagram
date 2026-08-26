from django.conf import settings
from django.http import JsonResponse
import logging

from core.services.rate_limit import check_rate_limit, identity_for_request

logger = logging.getLogger(__name__)


class RateLimitMiddleware:
    """Cache/Redis backed request throttling for production-sensitive endpoints."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        result = getattr(request, "rate_limit", None)
        if result is not None:
            response["X-RateLimit-Limit"] = str(result.limit)
            response["X-RateLimit-Remaining"] = str(result.remaining)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not getattr(settings, "RATE_LIMIT_ENABLED", True):
            return None

        resolver_match = getattr(request, "resolver_match", None)
        url_name = getattr(resolver_match, "url_name", "") or ""
        path = request.path or ""
        method = (request.method or "GET").upper()

        for rule in getattr(settings, "RATE_LIMIT_RULES", []):
            methods = [m.upper() for m in rule.get("methods", [])]
            if methods and method not in methods:
                continue

            url_names = set(rule.get("url_names", []))
            path_prefixes = tuple(rule.get("path_prefixes", []))
            paths = set(rule.get("paths", []))

            matched = (
                (url_name and url_name in url_names)
                or (path and path in paths)
                or (path_prefixes and path.startswith(path_prefixes))
            )
            if not matched:
                continue

            try:
                result = check_rate_limit(
                    namespace=rule.get("name", "default"),
                    identity=identity_for_request(request, rule.get("scope", "user_or_ip")),
                    rate=rule.get("rate", "120/m"),
                )
            except ValueError as exc:
                logger.error("Geçersiz rate-limit kuralı %s: %s", rule.get("name"), exc)
                continue
            if result.allowed:
                current = getattr(request, "rate_limit", None)
                if current is None or result.remaining < current.remaining:
                    request.rate_limit = result
                continue

            payload = {
                "success": False,
                "error": "rate_limited",
                "message": "Cok fazla istek gonderildi. Lutfen kisa bir sure sonra tekrar deneyin.",
                "retry_after": result.retry_after,
            }
            response = JsonResponse(payload, status=429)
            response["Retry-After"] = str(result.retry_after)
            response["X-RateLimit-Limit"] = str(result.limit)
            response["X-RateLimit-Remaining"] = str(result.remaining)
            return response

        return None
