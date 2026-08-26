import re

from django import template
from django.utils.html import format_html

register = template.Library()
DEFAULT_ICON = "fa-bell"
ICON_ALIASES = {
    "chart-line": "fa-chart-line", "chart_line": "fa-chart-line", "line-chart": "fa-chart-line",
    "bell": "fa-bell", "warning": "fa-triangle-exclamation", "error": "fa-circle-exclamation",
    "success": "fa-circle-check", "info": "fa-circle-info", "bullhorn": "fa-bullhorn",
}
FA_ICON_RE = re.compile(r"^fa-[a-z0-9-]+$")


def icon_parts(value):
    raw = str(value or "").strip()
    candidate = re.sub(r"^(fas|far|fab)\s+", "", raw.lower()).strip()
    candidate = ICON_ALIASES.get(candidate, candidate)
    if FA_ICON_RE.fullmatch(candidate):
        return "fontawesome", candidate
    if not raw or all(ord(char) < 128 for char in raw):
        return "fontawesome", DEFAULT_ICON
    return "emoji", raw[:8]


@register.filter
def notification_icon(value):
    kind, icon = icon_parts(value)
    if kind == "fontawesome":
        return format_html('<i class="fas {}" aria-hidden="true"></i>', icon)
    return icon
