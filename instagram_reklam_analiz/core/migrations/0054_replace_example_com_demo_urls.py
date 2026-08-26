from urllib.parse import urlsplit

from django.db import migrations


OLD_DOMAIN = "example.com"
NEW_BASE_URL = "https://reklamanaliz.net/rakip"


def _new_url(value):
    if not value:
        return value
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower()
    if hostname != OLD_DOMAIN and not hostname.endswith(f".{OLD_DOMAIN}"):
        return value

    identifier = hostname[: -len(f".{OLD_DOMAIN}")] if hostname != OLD_DOMAIN else "demo"
    identifier = identifier.strip(".") or "demo"
    path = parsed.path.strip("/")
    result = f"{NEW_BASE_URL}/{identifier}/"
    if path:
        result += path
    if parsed.query:
        result += f"?{parsed.query}"
    if parsed.fragment:
        result += f"#{parsed.fragment}"
    return result


def replace_demo_urls(apps, schema_editor):
    Competitor = apps.get_model("core", "Competitor")
    Ad = apps.get_model("core", "Ad")

    for competitor in Competitor.objects.exclude(website__isnull=True).exclude(website="").iterator():
        updated = _new_url(competitor.website)
        if updated != competitor.website:
            competitor.website = updated
            competitor.save(update_fields=["website"])

    for ad in Ad.objects.exclude(landing_url__isnull=True).exclude(landing_url="").iterator():
        updated = _new_url(ad.landing_url)
        if updated != ad.landing_url:
            ad.landing_url = updated
            ad.save(update_fields=["landing_url"])


class Migration(migrations.Migration):
    dependencies = [("core", "0053_backfill_ai_operation_tracking")]
    operations = [migrations.RunPython(replace_demo_urls, migrations.RunPython.noop)]
