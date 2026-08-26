from __future__ import annotations

from core.utils.html_translations import repair_mojibake


class HtmlLanguageResponseMiddleware:
    """Translate legacy hard-coded template text after HTML rendering.

    Newer screens use the `labels` context directly. This middleware is a
    compatibility layer for older templates that still contain static Turkish
    copy or mojibake text.
    """

    SKIP_PREFIXES = (
        "/admin/",
        "/api/",
        "/static/",
        "/media/",
        "/__debug__/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.session.get("preferred_language") != "tr":
            request.session["preferred_language"] = "tr"
        response = self.get_response(request)
        return self._process_response(request, response)

    def _process_response(self, request, response):
        if getattr(response, "streaming", False):
            return response
        if request.path.startswith(self.SKIP_PREFIXES):
            return response

        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type:
            return response
        if not getattr(response, "content", None):
            return response

        encoding = getattr(response, "charset", None) or "utf-8"
        try:
            html = response.content.decode(encoding)
        except UnicodeDecodeError:
            return response

        html = repair_mojibake(html)
        html = html.replace("Platinyum", "Platin").replace("Platinum", "Platin")

        response.content = html.encode(encoding)
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(response.content))
        return response
