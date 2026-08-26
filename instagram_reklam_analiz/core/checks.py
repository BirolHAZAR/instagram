from pathlib import Path

from django.conf import settings
from django.core.checks import Error, Warning, register
from core.services.rate_limit import parse_rate


MOJIBAKE_MARKERS = (
    "ğŸ",
    "ðŸ",
    "Â·",
    "â†",
    "âš",
    "âŒ",
    "Ã",
    "Ä±",
    "Å",
    "ï¸",
    "�",
)

CRITICAL_UI_FILES = (
    "core/templates/dashboard/executive.html",
    "core/views/dashboard_v2.py",
)


@register()
def check_critical_ui_encoding(app_configs, **kwargs):
    errors = []
    base_dir = Path(settings.BASE_DIR)

    for relative_path in CRITICAL_UI_FILES:
        path = base_dir / relative_path
        if not path.exists():
            continue

        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(marker in line for marker in MOJIBAKE_MARKERS):
                errors.append(
                    Error(
                        "Kritik UI dosyasında bozuk karakter/emoji kodlaması bulundu.",
                        hint=f"{relative_path}:{line_number} satırını düzeltin.",
                        obj=relative_path,
                        id="core.E001",
                    )
                )
                break

    return errors


@register(deploy=True)
def check_cache_and_rate_limit_deployment(app_configs, **kwargs):
    issues = []
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    if not settings.DEBUG and "locmem" in backend.lower():
        issues.append(Error("Canlı ortamda LocMem cache kullanılamaz; workerlar rate-limit ve cache verisini paylaşamaz.", id="core.E010"))
    if not getattr(settings, "RATE_LIMIT_ENABLED", False):
        issues.append(Warning("Uygulama rate-limit sistemi kapalı.", id="core.W011"))
    for rule in getattr(settings, "RATE_LIMIT_RULES", []):
        try:
            parse_rate(rule.get("rate"))
        except ValueError:
            issues.append(Error(f"Geçersiz rate-limit değeri: {rule.get('name')}={rule.get('rate')}", id="core.E012"))
    return issues
