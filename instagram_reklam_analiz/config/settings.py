"""
Django settings for config project.
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

from decouple import config
from celery.schedules import crontab
from kombu import Queue

import sentry_sdk
from django.utils.translation import gettext_lazy as _

# Sentry Konfigürasyonu
SENTRY_DSN = os.getenv('SENTRY_DSN', '')
DJANGO_ENV = os.getenv('DJANGO_ENV', 'development')
SENTRY_STARTUP_LOG = os.getenv('SENTRY_STARTUP_LOG', 'false').lower() in {'1', 'true', 'yes'}


def _is_runserver_reloader_parent():
    return "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true"


if SENTRY_DSN and not _is_runserver_reloader_parent():
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=DJANGO_ENV,
    )

    if SENTRY_STARTUP_LOG:
        print(f"Sentry entegrasyonu aktif (Environment: {DJANGO_ENV})")
elif not SENTRY_DSN and SENTRY_STARTUP_LOG:
    print("Sentry DSN bulunamadi; hata takibi devre disi.")



# Proje dizini
BASE_DIR = Path(__file__).resolve().parent.parent

# Runtime klasörü
# Celery Beat gibi çalışma zamanı dosyaları proje root yerine burada tutulur.
RUNTIME_DIR = BASE_DIR / "runtime"
CELERYBEAT_RUNTIME_DIR = RUNTIME_DIR / "celerybeat"
os.makedirs(CELERYBEAT_RUNTIME_DIR, exist_ok=True)

# .env dosyasından değerleri oku (decouple zaten .env okur)
SECRET_KEY = config('SECRET_KEY', default='django-insecure-default-key-change-this')
TOKEN_ENCRYPTION_KEY = os.getenv('TOKEN_ENCRYPTION_KEY', '')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config(
    'ALLOWED_HOSTS',
    default='localhost,127.0.0.1,reklamanaliz.net,www.reklamanaliz.net',
).split(',')
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in config(
        "CSRF_TRUSTED_ORIGINS",
        default="https://reklamanaliz.net,https://www.reklamanaliz.net",
        cast=str,
    ).split(",")
    if origin.strip()
]

# Production security defaults. DEBUG=True iken lokal geliştirmeyi bozmaz.
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=not DEBUG, cast=bool)
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=not DEBUG, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=not DEBUG, cast=bool)
# The production container is only reachable through the trusted Nginx/Traefik
# proxy chain, which reports the original client scheme with this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = config("USE_X_FORWARDED_HOST", default=not DEBUG, cast=bool)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = config("CSRF_COOKIE_HTTPONLY", default=False, cast=bool)
CSRF_FAILURE_VIEW = "core.views.csrf.csrf_failure"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = config("SECURE_REFERRER_POLICY", default="same-origin")
X_FRAME_OPTIONS = config("X_FRAME_OPTIONS", default="DENY")
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0 if DEBUG else 31536000, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=not DEBUG, cast=bool)
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=False, cast=bool)

# MySQL Veritabanı (SADECE BİR TANIM)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='reklam_analiz'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default='123'),
        'HOST': config('DB_HOST', default='127.0.0.1'),
        'PORT': config('DB_PORT', default='5432'),
        # A stalled VM/NAT port must not hold every web request open for minutes.
        'OPTIONS': {
            'connect_timeout': config('DB_CONNECT_TIMEOUT', default=5, cast=int),
        },
        # Reuse healthy connections instead of opening a new TCP connection per request.
        'CONN_MAX_AGE': config('DB_CONN_MAX_AGE', default=60, cast=int),
        'CONN_HEALTH_CHECKS': True,
    }
}

# Instagram API Ayarları (SADECE BİR TANIM)
INSTAGRAM_APP_ID = config('INSTAGRAM_APP_ID', default='')
INSTAGRAM_APP_SECRET = config('INSTAGRAM_APP_SECRET', default='')
INSTAGRAM_ACCESS_TOKEN = config('INSTAGRAM_ACCESS_TOKEN', default='')
INSTAGRAM_REDIRECT_URI = config('INSTAGRAM_REDIRECT_URI', default='http://localhost:8000/instagram/callback/')
INSTAGRAM_API_VERSION = config('INSTAGRAM_API_VERSION', default='v25.0')
INSTAGRAM_BASE_URL = config('INSTAGRAM_BASE_URL', default='https://graph.instagram.com')
FACEBOOK_GRAPH_URL = config('FACEBOOK_GRAPH_URL', default='https://graph.facebook.com/v25.0')
META_AD_LIBRARY_ACCESS_TOKEN = config('META_AD_LIBRARY_ACCESS_TOKEN', default=INSTAGRAM_ACCESS_TOKEN)
META_AD_LIBRARY_COUNTRIES = [
    item.strip().upper()
    for item in config('META_AD_LIBRARY_COUNTRIES', default='TR').split(',')
    if item.strip()
]
META_AD_LIBRARY_SEARCH_TYPE = config('META_AD_LIBRARY_SEARCH_TYPE', default='KEYWORD_UNORDERED')
META_AD_LIBRARY_AD_TYPE = config('META_AD_LIBRARY_AD_TYPE', default='ALL')
META_AD_LIBRARY_ACTIVE_STATUS = config('META_AD_LIBRARY_ACTIVE_STATUS', default='ALL')
META_AD_LIBRARY_COUNTRIES_FORMAT = config('META_AD_LIBRARY_COUNTRIES_FORMAT', default='comma')
META_AD_LIBRARY_LIMIT = config('META_AD_LIBRARY_LIMIT', default=50, cast=int)

# Facebook OAuth
FACEBOOK_APP_ID = os.getenv('FACEBOOK_APP_ID')
FACEBOOK_APP_SECRET = os.getenv('FACEBOOK_APP_SECRET')
FACEBOOK_REDIRECT_URI = config('FACEBOOK_REDIRECT_URI', default='http://localhost:8000/connect/facebook/callback/')

# Organic publishing. Keep disabled unless production Meta app review, scopes,
# page/IG business account ids and public media URLs are fully configured.
ORGANIC_INSTAGRAM_PUBLISH_ENABLED = config('ORGANIC_INSTAGRAM_PUBLISH_ENABLED', default=False, cast=bool)
ORGANIC_FACEBOOK_PUBLISH_ENABLED = config('ORGANIC_FACEBOOK_PUBLISH_ENABLED', default=False, cast=bool)
ORGANIC_TIKTOK_PUBLISH_ENABLED = config('ORGANIC_TIKTOK_PUBLISH_ENABLED', default=True, cast=bool)
ORGANIC_X_PUBLISH_ENABLED = config('ORGANIC_X_PUBLISH_ENABLED', default=True, cast=bool)
ORGANIC_LINKEDIN_PUBLISH_ENABLED = config('ORGANIC_LINKEDIN_PUBLISH_ENABLED', default=True, cast=bool)
LINKEDIN_API_VERSION = config('LINKEDIN_API_VERSION', default='202603')

# OpenAI
OPENAI_API_KEY = config('OPENAI_API_KEY', default='')
OPENAI_USAGE_API_KEY = config('OPENAI_USAGE_API_KEY', default=OPENAI_API_KEY)
OPENAI_USAGE_CYCLE_START_DATE = config('OPENAI_USAGE_CYCLE_START_DATE', default='2026-06-26')
OPENAI_MODEL = config('OPENAI_MODEL', default='gpt-5.6-terra')
OPENAI_SHOPPING_VISION_MODEL = config('OPENAI_SHOPPING_VISION_MODEL', default='gpt-5.6-sol')
OPENAI_SHOPPING_PROMPT_MODEL = config('OPENAI_SHOPPING_PROMPT_MODEL', default='gpt-5.6-sol')
OPENAI_SHOPPING_PREFILTER_MODEL = config('OPENAI_SHOPPING_PREFILTER_MODEL', default='gpt-5.6-luna')
OPENAI_SHOPPING_MATCH_MODEL = config('OPENAI_SHOPPING_MATCH_MODEL', default='gpt-5.6-terra')
OPENAI_SHOPPING_QA_MODEL = config('OPENAI_SHOPPING_QA_MODEL', default='gpt-5.6-sol')
OPENAI_SHOPPING_FALLBACK_MODEL = config('OPENAI_SHOPPING_FALLBACK_MODEL', default='gpt-5.6-terra')
OPENAI_CREATIVE_ANALYSIS_MODEL = config('OPENAI_CREATIVE_ANALYSIS_MODEL', default='gpt-5.6-sol')
OPENAI_CREATIVE_WORK_MODEL = config('OPENAI_CREATIVE_WORK_MODEL', default='gpt-5.6-terra')
OPENAI_CREATIVE_QA_MODEL = config('OPENAI_CREATIVE_QA_MODEL', default='gpt-5.6-sol')
OPENAI_IMAGE_MODEL = config('OPENAI_IMAGE_MODEL', default='gpt-image-2')
OPENAI_VIDEO_MODEL = config('OPENAI_VIDEO_MODEL', default='sora-2')
OPENAI_MAX_TOKENS = config('OPENAI_MAX_TOKENS', default=1000, cast=int)
OPENAI_TEMPERATURE = config('OPENAI_TEMPERATURE', default=0.7, cast=float)
TAVILY_API_KEY = config('TAVILY_API_KEY', default='')
SERPAPI_API_KEY = config('SERPAPI_API_KEY', default='')
MARKET_RESEARCH_MAX_RESULTS = config('MARKET_RESEARCH_MAX_RESULTS', default=8, cast=int)
SHOPPING_AGENT_MAX_SMART_SOURCES = config('SHOPPING_AGENT_MAX_SMART_SOURCES', default=6, cast=int)
SHOPPING_AGENT_IMMERSIVE_PRODUCT_LIMIT = config('SHOPPING_AGENT_IMMERSIVE_PRODUCT_LIMIT', default=5, cast=int)

# Email (Geliştirme için console, production için SMTP)
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_USE_SSL = config('EMAIL_USE_SSL', default=False, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER)
SERVER_EMAIL = config('SERVER_EMAIL', default=EMAIL_HOST_USER)
REPORTS_FROM_EMAIL = config('REPORTS_FROM_EMAIL', default=DEFAULT_FROM_EMAIL)
CONTACT_FROM_EMAIL = config('CONTACT_FROM_EMAIL', default=DEFAULT_FROM_EMAIL)
CONTACT_TO_EMAIL = config('CONTACT_TO_EMAIL', default=CONTACT_FROM_EMAIL)
DEMO_REQUEST_FROM_EMAIL = config('DEMO_REQUEST_FROM_EMAIL', default=DEFAULT_FROM_EMAIL)
DEMO_REQUEST_TO_EMAIL = config('DEMO_REQUEST_TO_EMAIL', default=DEMO_REQUEST_FROM_EMAIL)
EMAIL_SUBJECT_PREFIX = '[ReklamAnaliz] '
EMAIL_TIMEOUT = config('EMAIL_TIMEOUT', default=30, cast=int)

# WhatsApp contact line. Use country code without +, spaces, or leading zero.
WHATSAPP_PHONE_NUMBER = config("WHATSAPP_PHONE_NUMBER", default="")
WHATSAPP_MESSAGE = config(
    "WHATSAPP_MESSAGE",
    default="Merhaba, ReklamAnaliz.net hakkinda bilgi almak istiyorum.",
)

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django_extensions',
    'django.contrib.sites',
    'django.contrib.humanize',
    'rest_framework',
    'daphne',
    'channels',
    'django.contrib.staticfiles',
    'crispy_forms',
    'crispy_bootstrap5',
    "core.apps.CoreConfig",
    'django_celery_results',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.mfa',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.facebook',
    'allauth.socialaccount.providers.instagram',
    'allauth.socialaccount.providers.tiktok',
    'allauth.socialaccount.providers.linkedin_oauth2',
    'allauth.socialaccount.providers.twitter_oauth2',
]


MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',      # Session önce
    "django.middleware.locale.LocaleMiddleware",
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',                # CSRF mutlaka burada
    'allauth.account.middleware.AccountMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',  # Auth sonra
    'core.middleware.maintenance_mode.MaintenanceModeMiddleware',
    'core.middleware.account_lifecycle.PendingDeletionAccountMiddleware',
    'core.middleware.subscription_access.SubscriptionAccessMiddleware',
    'core.middleware.rate_limit.RateLimitMiddleware',
    'core.middleware.agency_permissions.AgencyMenuPermissionMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'core.middleware.concurrent_sessions.ConcurrentSessionMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.language_response.HtmlLanguageResponseMiddleware',
    'core.middleware.cache_headers.CacheControlMiddleware',
]

ROOT_URLCONF = 'config.urls'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'core/templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'builtins': [
                'core.templatetags.tr_numbers',
            ],
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.alert_notifications',
                 "core.context_processors.language_labels",
                "core.context_processors.auth_security_links",
                "core.context_processors.whatsapp_contact",
                "core.context_processors.agency_client_scope",
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'tr'
TIME_ZONE = 'Europe/Istanbul'
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ("tr", _("Türkçe")),
]

LOCALE_PATHS = [
    BASE_DIR / "locale",
]



# Static files
STATIC_URL = '/static/'
SITE_URL = config("SITE_URL", default="https://www.reklamanaliz.net").rstrip("/")
PUBLIC_MEDIA_BASE_URL = config("PUBLIC_MEDIA_BASE_URL", default=SITE_URL).rstrip("/")
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
WHITENOISE_MAX_AGE = 31536000 if not DEBUG else 0

# Media files (SADECE BİR TANIM)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
os.makedirs(MEDIA_ROOT, exist_ok=True)


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Crispy Forms
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# Yönlendirmeler
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# ============================================
# DJANGO-ALLAUTH AYARLARI (GÜNCEL VERSİYON)
# ============================================

# Site ID (admin panelinden ayarlanacak)
SITE_ID = 1

# Authentication backends
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# Login Methods - YENİ (ACCOUNT_AUTHENTICATION_METHOD yerine)
ACCOUNT_LOGIN_METHODS = {'username', 'email'}  # username ve email ile giriş

# Signup Fields - YENİ (ACCOUNT_EMAIL_REQUIRED ve ACCOUNT_USERNAME_REQUIRED yerine)
ACCOUNT_SIGNUP_FIELDS = ['email*', 'username*', 'password1*', 'password2*']

# Email verification
ACCOUNT_EMAIL_VERIFICATION = config("ACCOUNT_EMAIL_VERIFICATION", default="mandatory")
ACCOUNT_EMAIL_VERIFICATION_BY_CODE_ENABLED = config("ACCOUNT_EMAIL_VERIFICATION_BY_CODE_ENABLED", default=False, cast=bool)
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_EMAIL_SUBJECT_PREFIX = '[ReklamAnaliz] '
ACCOUNT_CONFIRM_EMAIL_ON_GET = True
ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS = 3

SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_EMAIL_VERIFICATION = config("SOCIALACCOUNT_EMAIL_VERIFICATION", default="optional")
SOCIALACCOUNT_QUERY_EMAIL = True
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online", "prompt": "select_account"},
    },
    "facebook": {
        "METHOD": "oauth2",
        "SCOPE": ["email", "public_profile"],
        "FIELDS": ["id", "email", "name", "first_name", "last_name"],
    },
    "instagram": {
        "SCOPE": ["user_profile"],
    },
    "tiktok": {
        "SCOPE": ["user.info.basic", "video.publish"],
    },
    "linkedin_oauth2": {
        "SCOPE": ["openid", "profile", "email", "w_member_social"],
    },
    "twitter_oauth2": {
        "SCOPE": ["users.read", "tweet.read", "tweet.write", "offline.access"],
    },
}

MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]
MFA_TRUST_ENABLED = config("MFA_TRUST_ENABLED", default=True, cast=bool)
MFA_TRUST_COOKIE_AGE = config("MFA_TRUST_COOKIE_AGE", default=60 * 60 * 24 * 30, cast=int)
MFA_PASSKEY_LOGIN_ENABLED = config("MFA_PASSKEY_LOGIN_ENABLED", default=False, cast=bool)
MFA_PASSKEY_SIGNUP_ENABLED = config("MFA_PASSKEY_SIGNUP_ENABLED", default=False, cast=bool)

# Rate limits - allauth 65.x anahtarları.
# Canlıda brute-force ve spam denemelerine karşı kapalı bırakılmamalı.
ACCOUNT_RATE_LIMITS = {
    "login": config("ACCOUNT_RATE_LIMIT_LOGIN", default="30/m/ip"),
    "login_failed": config("ACCOUNT_RATE_LIMIT_LOGIN_FAILED", default="10/m/ip,5/300s/key"),
    "signup": config("ACCOUNT_RATE_LIMIT_SIGNUP", default="10/m/ip"),
    "reset_password": config("ACCOUNT_RATE_LIMIT_RESET_PASSWORD", default="20/m/ip,5/m/key"),
    "reset_password_from_key": config("ACCOUNT_RATE_LIMIT_RESET_PASSWORD_FROM_KEY", default="20/m/ip"),
    "change_password": config("ACCOUNT_RATE_LIMIT_CHANGE_PASSWORD", default="5/m/user"),
    "manage_email": config("ACCOUNT_RATE_LIMIT_MANAGE_EMAIL", default="10/m/user"),
}

# App-level rate limits. Redis cache aktifse bu sayaçlar Redis üzerinde çalışır.
RATE_LIMIT_ENABLED = config("RATE_LIMIT_ENABLED", default=True, cast=bool)
RATE_LIMIT_TRUSTED_PROXIES = [value.strip() for value in config("RATE_LIMIT_TRUSTED_PROXIES", default="127.0.0.1,::1").split(",") if value.strip()]
RATE_LIMIT_CONTROL_TOWER_AI = config("RATE_LIMIT_CONTROL_TOWER_AI", default="6/h")
TAVILY_MONTHLY_LIMIT = config("TAVILY_MONTHLY_LIMIT", default=1000, cast=int)
TAVILY_RATE_LIMIT = config("TAVILY_RATE_LIMIT", default="100/m")
RATE_LIMIT_RULES = [
    {
        "name": "auth",
        "paths": ["/accounts/login/", "/accounts/signup/", "/accounts/password/reset/", "/admin/login/", "/admin/logout/"],
        "methods": ["GET", "POST"],
        "scope": "ip",
        "rate": config("RATE_LIMIT_AUTH", default="30/m"),
    },
    {
        "name": "api_default",
        "path_prefixes": ["/api/"],
        "methods": ["GET", "POST"],
        "scope": "user_or_ip",
        "rate": config("RATE_LIMIT_API", default="180/m"),
    },
    {
        "name": "api_write",
        "path_prefixes": ["/api/"],
        "methods": ["POST", "PUT", "PATCH", "DELETE"],
        "scope": "user_or_ip",
        "rate": config("RATE_LIMIT_API_WRITE", default="45/m"),
    },
    {
        "name": "ai",
        "url_names": [
            "ai_analyze_campaign",
            "ai_analyze_account",
            "ai_suggestions_api",
            "start_ad_ai_analysis",
            "save_ai_analysis",
            "generate_content_api",
            "creative_reference_prompt",
        ],
        "methods": ["GET", "POST"],
        "scope": "user_or_ip",
        "rate": config("RATE_LIMIT_AI", default="20/m"),
    },
    {
        "name": "sync",
        "url_names": [
            "api_sync_account",
            "api_campaign_panel_sync_account",
            "api_rakip_reklam_sync",
            "sync_instagram_data",
            "organic_content_sync_account",
        ],
        "methods": ["POST"],
        "scope": "user_or_ip",
        "rate": config("RATE_LIMIT_SYNC", default="6/m"),
    },
    {
        "name": "publish",
        "url_names": ["creative_publish", "organic_content_publish", "send_to_instagram"],
        "methods": ["POST"],
        "scope": "user_or_ip",
        "rate": config("RATE_LIMIT_PUBLISH", default="10/m"),
    },
    {
        "name": "report_send",
        "url_names": ["scheduled_report_send_now", "send_analysis_email"],
        "methods": ["POST"],
        "scope": "user_or_ip",
        "rate": config("RATE_LIMIT_REPORT_SEND", default="5/m"),
    },
    {
        "name": "optimization",
        "url_names": ["ajax_optimize_reklam"],
        "methods": ["POST"],
        "scope": "user_or_ip",
        "rate": config("RATE_LIMIT_OPTIMIZATION", default="20/m"),
    },
]
# Web ve Celery ürün araştırma cache'ini aynı Redis alanında paylaşır.
REDIS_URL = config("REDIS_URL", default="").strip()


def _redis_url_for_db(base_url: str, db: int) -> str:
    """Keep provider credentials/options and select a logical Redis database."""
    parts = urlsplit(base_url)
    if parts.scheme not in {"redis", "rediss"} or not parts.netloc:
        raise ValueError("REDIS_URL must be a valid redis:// or rediss:// URL")
    return urlunsplit((parts.scheme, parts.netloc, f"/{db}", parts.query, parts.fragment))


CACHE_REDIS_URL = config("CACHE_REDIS_URL", default="")
if not CACHE_REDIS_URL and REDIS_URL:
    CACHE_REDIS_URL = _redis_url_for_db(REDIS_URL, 3)
if not CACHE_REDIS_URL and not DEBUG:
    _cache_host = config("REDIS_HOST", default="127.0.0.1")
    _cache_port = config("REDIS_PORT", default="6379")
    _cache_password = config("REDIS_PASSWORD", default="")
    _cache_auth = f":{_cache_password}@" if _cache_password else ""
    CACHE_REDIS_URL = f"redis://{_cache_auth}{_cache_host}:{_cache_port}/3"
if CACHE_REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_REDIS_URL,
            "KEY_PREFIX": "reklamanaliz",
            "TIMEOUT": 300,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "reklamanaliz-local",
        }
    }
# Redirects
ACCOUNT_LOGOUT_REDIRECT_URL = '/'
ACCOUNT_LOGIN_REDIRECT_URL = '/dashboard/'
ACCOUNT_SIGNUP_REDIRECT_URL = '/hesap-ekle/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'
LOGIN_URL = '/accounts/login/'

# Session
ACCOUNT_SESSION_REMEMBER = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = config("SESSION_EXPIRE_AT_BROWSER_CLOSE", default=True, cast=bool)
SESSION_COOKIE_AGE = config("SESSION_COOKIE_AGE", default=60 * 60 * 2, cast=int)
SESSION_SAVE_EVERY_REQUEST = config("SESSION_SAVE_EVERY_REQUEST", default=True, cast=bool)

# Email
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_USERNAME_MIN_LENGTH = 3

# Additional settings
ACCOUNT_USER_DISPLAY = lambda user: user.username
ACCOUNT_PREVENT_ENUMERATION = True  # Kullanıcı adı/enumeration koruması
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True
ACCOUNT_ADAPTER = "core.adapters.AccountAdapter"

# AI Settings
AI_ANALYSIS_ENABLED = config('AI_ANALYSIS_ENABLED', default=True, cast=bool)
AI_AUTO_REPORT = config('AI_AUTO_REPORT', default=True, cast=bool)
AI_CREDITS_ENFORCED = config("AI_CREDITS_ENFORCED", default=True, cast=bool)
TRIAL_ENABLED = config("TRIAL_ENABLED", default=True, cast=bool)
TRIAL_DAYS = config("TRIAL_DAYS", default=14, cast=int)
TRIAL_AI_CREDITS = config("TRIAL_AI_CREDITS", default=50, cast=int)
SUBSCRIPTION_ACCESS_ENFORCED = config("SUBSCRIPTION_ACCESS_ENFORCED", default=True, cast=bool)
SUBSCRIPTION_ACCESS_ALLOWED_PREFIXES = [
    prefix.strip()
    for prefix in config(
        "SUBSCRIPTION_ACCESS_ALLOWED_PREFIXES",
        default="/static/,/media/,/admin/,/accounts/,/login/,/signup/,/logout/,/pricing/,/checkout/,/payment/,/i18n/",
    ).split(",")
    if prefix.strip()
]

# ============================================
# REDIS / CELERY / CHANNELS AYARLARI
# Profesyonel yapı: broker, result backend ve websocket Redis DB ayrıdır.
# ============================================

REDIS_HOST = config("REDIS_HOST", default="127.0.0.1")
REDIS_PORT = config("REDIS_PORT", default="6379")
REDIS_PASSWORD = config("REDIS_PASSWORD", default="")

def _redis_url(db: int) -> str:
    if REDIS_URL:
        return _redis_url_for_db(REDIS_URL, db)
    auth = f":{REDIS_PASSWORD}@" if REDIS_PASSWORD else ""
    return f"redis://{auth}{REDIS_HOST}:{REDIS_PORT}/{db}"

CELERY_BROKER_URL = config("CELERY_BROKER_URL", default=_redis_url(0))
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default=_redis_url(1))
CHANNEL_REDIS_URL = config("CHANNEL_REDIS_URL", default=_redis_url(2))

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [CHANNEL_REDIS_URL],
        },
    },
}

CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = False
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60
CELERY_RESULT_EXPIRES = 60 * 60 * 24 * 7
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE_FILENAME = str(CELERYBEAT_RUNTIME_DIR / "celerybeat-schedule")
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_QUEUES = (
    Queue("default"),
    Queue("sync"),
    Queue("ai"),
    Queue("marketplace"),
    Queue("maintenance"),
    Queue("billing"),
    Queue("reports"),
    Queue("notifications"),
)
CELERY_TASK_ROUTES = {
    "core.tasks.sync_tasks.*": {"queue": "sync"},
    "core.tasks.v2_platform_sync.*": {"queue": "sync"},
    "core.tasks.platform_tasks.*": {"queue": "sync"},
    "core.tasks.competitor_sync.*": {"queue": "sync"},
    "core.tasks.metric_tasks.*": {"queue": "sync"},
    "core.tasks.marketplace_sync.*": {"queue": "marketplace"},
    "core.tasks.control_tower_ai.*": {"queue": "ai"},
    "core.tasks.ai_analysis.*": {"queue": "ai"},
    "core.tasks.analysis_tasks.*": {"queue": "ai"},
    "core.tasks.budget_tasks.*": {"queue": "ai"},
    "core.tasks.budget.*": {"queue": "ai"},
    "core.tasks.report_tasks.*": {"queue": "reports"},
    "core.tasks.notification_tasks.*": {"queue": "notifications"},
    "core.tasks.notifications.*": {"queue": "notifications"},
    "core.tasks.maintenance_tasks.*": {"queue": "maintenance"},
    "core.tasks.maintenance.*": {"queue": "maintenance"},
    "core.tasks.admin_ops.sync_openai_usage": {"queue": "billing"},
    "core.tasks.admin_ops.dispatch_admin_managed_schedules": {"queue": "maintenance"},
    "core.tasks.admin_ops.refresh_expired_tokens": {"queue": "maintenance"},
    "core.tasks.admin_ops.refresh_due_marketplace_researches": {"queue": "marketplace"},
    "core.tasks.admin_ops.generate_octo_tasks": {"queue": "ai"},
    "core.tasks.admin_ops.dispatch_octo_rule_engine_sweep": {"queue": "ai"},
}

# Celery Beat Schedule
# Not: Beat planı tek merkezde burada tutulur. config/celery.py içinde schedule tanımlanmaz.
CELERY_BEAT_SCHEDULE = {
    "dispatch-lifecycle-emails": {
        "task": "core.tasks.communications.dispatch_lifecycle_emails",
        "schedule": crontab(hour=10, minute=0),
        "options": {"expires": 60 * 60 * 6, "queue": "notifications"},
    },
    "dispatch-announcements": {
        "task": "core.tasks.communications.dispatch_announcements",
        "schedule": crontab(minute="*/5"),
        "options": {"expires": 60 * 4, "queue": "notifications"},
    },
    "dispatch-octo-rule-engine-sweep": {
        "task": "core.tasks.admin_ops.dispatch_octo_rule_engine_sweep",
        "schedule": crontab(minute="*/30"),
        "kwargs": {"trigger": "periodic_sweep"},
        "options": {"expires": 60 * 25, "queue": "ai"},
    },
    "scan-critical-alerts": {
        "task": "core.tasks.notification_tasks.scan_critical_alerts_for_all_users",
        "schedule": crontab(minute=15, hour="*/2"),
        "options": {"expires": 60 * 60, "queue": "notifications"},
    },
    "refresh-user-alerts-daily": {
        "task": "core.tasks.notification_tasks.refresh_all_users_alerts",
        "schedule": crontab(hour=9, minute=0),
        "options": {"expires": 60 * 60 * 2, "queue": "notifications"},
    },
    "send-daily-notification-summaries": {
        "task": "core.tasks.notification_tasks.send_daily_notification_summaries",
        "schedule": crontab(hour=18, minute=0),
        "options": {"expires": 60 * 60 * 2, "queue": "notifications"},
    },
    "sync-all-platform-accounts": {
        "task": "core.tasks.sync_tasks.sync_all_platform_accounts",
        "schedule": crontab(minute="*/30"),
        "options": {"expires": 60 * 25, "queue": "sync"},
    },
    "sync-live-competitor-ads": {
        "task": "core.tasks.competitor_sync.sync_all_live_competitors",
        "schedule": crontab(minute="*/30"),
        "options": {"expires": 60 * 25, "queue": "sync"},
    },
    "sync-due-organic-posts": {
        "task": "core.tasks.sync_tasks.sync_due_organic_accounts",
        "schedule": crontab(minute="*/30"),
        "options": {"expires": 60 * 25, "queue": "sync"},
    },
    "sync-due-marketplace-accounts": {
        "task": "core.tasks.marketplace_sync.sync_due_marketplace_accounts",
        "schedule": crontab(minute="*/30"),
        "options": {"expires": 60 * 25, "queue": "marketplace"},
    },
    "record-daily-metrics": {
        "task": "core.tasks.metric_tasks.record_daily_metrics_for_all_ads",
        "schedule": crontab(hour=23, minute=59),
        "options": {"expires": 60 * 60, "queue": "sync"},
    },
    "refresh-daily-demo-metrics": {
        "task": "core.tasks.metric_tasks.refresh_daily_demo_metrics",
        "schedule": crontab(hour=0, minute=10),
        "options": {"expires": 60 * 60 * 6, "queue": "sync"},
    },
    "cleanup-old-metrics": {
        "task": "core.tasks.metric_tasks.cleanup_old_metric_history",
        "schedule": crontab(day_of_month=1, hour=2, minute=0),
        "kwargs": {"days_to_keep": 90},
        "options": {"expires": 60 * 60 * 6, "queue": "maintenance"},
    },
    "refresh-expired-tokens": {
        "task": "core.tasks.maintenance_tasks.refresh_expired_tokens",
        "schedule": crontab(minute=5, hour="*/1"),
        "options": {"expires": 60 * 60, "queue": "maintenance"},
    },
    "sync-openai-usage": {
        "task": "core.tasks.admin_ops.sync_openai_usage",
        "schedule": crontab(minute=10, hour="*/6"),
        "options": {"expires": 60 * 60 * 2, "queue": "billing"},
    },
    "clean-old-raw-data": {
        "task": "core.tasks.maintenance_tasks.cleanup_old_raw_data",
        "schedule": crontab(day_of_month=1, hour=3, minute=0),
        "kwargs": {"days": 30},
        "options": {"expires": 60 * 60 * 6, "queue": "maintenance"},
    },
    "purge-expired-pending-deletion-accounts": {
        "task": "core.tasks.maintenance_tasks.sync_account_deletion_lifecycle",
        "schedule": crontab(hour=3, minute=30),
        "kwargs": {"limit": 100},
        "options": {"expires": 60 * 60 * 2, "queue": "maintenance"},
    },
    "process-due-subscription-renewals": {
        "task": "core.tasks.maintenance_tasks.process_due_subscription_renewals",
        "schedule": crontab(hour=4, minute=0),
        "kwargs": {"limit": 100},
        "options": {"expires": 60 * 60 * 2, "queue": "billing"},
    },
    "generate-weekly-report": {
        "task": "core.tasks.report_tasks.generate_weekly_report",
        "schedule": crontab(day_of_week=1, hour=8, minute=0),
        "options": {"expires": 60 * 60 * 12, "queue": "reports"},
    },
    "dispatch-due-scheduled-reports": {
        "task": "core.tasks.report_tasks.dispatch_due_scheduled_reports",
        "schedule": crontab(minute=5),
        "options": {"expires": 60 * 30, "queue": "reports"},
    },
    "refresh-tracked-marketplace-researches": {
        "task": "core.tasks.marketplace_sync.refresh_tracked_marketplace_researches",
        "schedule": crontab(minute=20, hour="*/1"),
        "kwargs": {"limit": 50},
        "options": {"expires": 60 * 45, "queue": "marketplace"},
    },
    "dispatch-admin-managed-schedules": {
        "task": "core.tasks.admin_ops.dispatch_admin_managed_schedules",
        "schedule": crontab(minute="*"),
        "options": {"expires": 55, "queue": "maintenance"},
    },
}
REFERRAL_PROGRAM_ENABLED = os.getenv("REFERRAL_PROGRAM_ENABLED", "1").lower() in {"1", "true", "yes", "on"}
