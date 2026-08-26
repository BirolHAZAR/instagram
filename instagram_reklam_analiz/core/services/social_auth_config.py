import os

from django.conf import settings
from django.contrib.sites.models import Site


SOCIAL_PROVIDER_CONFIG = [
    {
        "id": "google",
        "name": "Google",
        "env_client_id": "GOOGLE_CLIENT_ID",
        "env_secret": "GOOGLE_CLIENT_SECRET",
        "callback_path": "/accounts/google/login/callback/",
    },
    {
        "id": "facebook",
        "name": "Facebook",
        "env_client_id": "FACEBOOK_APP_ID",
        "env_secret": "FACEBOOK_APP_SECRET",
        "callback_path": "/accounts/facebook/login/callback/",
    },
    {
        "id": "instagram",
        "name": "Instagram",
        "env_client_id": "INSTAGRAM_APP_ID",
        "env_secret": "INSTAGRAM_APP_SECRET",
        "callback_path": "/accounts/instagram/login/callback/",
    },
    {
        "id": "tiktok",
        "name": "TikTok",
        "env_client_id": "TIKTOK_CLIENT_KEY",
        "env_secret": "TIKTOK_CLIENT_SECRET",
        "callback_path": "/accounts/tiktok/login/callback/",
    },
    {
        "id": "linkedin_oauth2",
        "name": "LinkedIn",
        "env_client_id": "LINKEDIN_CLIENT_ID",
        "env_secret": "LINKEDIN_CLIENT_SECRET",
        "callback_path": "/accounts/linkedin_oauth2/login/callback/",
    },
    {
        "id": "twitter_oauth2",
        "name": "X",
        "env_client_id": "X_CLIENT_ID",
        "env_secret": "X_CLIENT_SECRET",
        "callback_path": "/accounts/twitter_oauth2/login/callback/",
    },
]


def current_site():
    domain = os.getenv("SITE_DOMAIN") or os.getenv("PUBLIC_DOMAIN") or "reklamanaliz.net"
    name = os.getenv("SITE_NAME") or "reklamanaliz.net"
    site, _created = Site.objects.get_or_create(
        id=getattr(settings, "SITE_ID", 1),
        defaults={"domain": domain, "name": name},
    )
    changed = False
    if site.domain != domain:
        site.domain = domain
        changed = True
    if site.name != name:
        site.name = name
        changed = True
    if changed:
        site.save(update_fields=["domain", "name"])
    return site


def provider_rows():
    from allauth.socialaccount.models import SocialApp

    site = current_site()
    apps = {
        app.provider: app
        for app in SocialApp.objects.filter(provider__in=[item["id"] for item in SOCIAL_PROVIDER_CONFIG])
    }
    rows = []
    for item in SOCIAL_PROVIDER_CONFIG:
        app = apps.get(item["id"])
        client_id = os.getenv(item["env_client_id"], "")
        secret = os.getenv(item["env_secret"], "")
        rows.append({
            **item,
            "site": site,
            "site_domain": site.domain,
            "app": app,
            "configured": bool(app and app.client_id and app.secret),
            "env_ready": bool(client_id and secret),
            "env_client_id_set": bool(client_id),
            "env_secret_set": bool(secret),
            "callback_url": f"https://{site.domain}{item['callback_path']}",
            "login_url": f"/accounts/{item['id']}/login/",
            "admin_add_url": f"/admin/socialaccount/socialapp/add/?provider={item['id']}&name={item['name']}",
            "admin_change_url": f"/admin/socialaccount/socialapp/{app.id}/change/" if app else "",
        })
    return rows


def sync_social_apps_from_env(stdout=None):
    from allauth.socialaccount.models import SocialApp

    site = current_site()
    results = []
    for item in SOCIAL_PROVIDER_CONFIG:
        client_id = os.getenv(item["env_client_id"], "").strip()
        secret = os.getenv(item["env_secret"], "").strip()
        if not client_id or not secret:
            results.append((item["id"], "skipped"))
            continue
        app = SocialApp.objects.filter(provider=item["id"]).order_by("id").first()
        created = app is None
        if app is None:
            app = SocialApp(provider=item["id"])
        app.name = item["name"]
        app.client_id = client_id
        app.secret = secret
        app.save()
        app.sites.set([site])
        results.append((item["id"], "created" if created else "updated"))
        if stdout:
            stdout.write(f"{item['name']}: {'olusturuldu' if created else 'guncellendi'}")
    return results
