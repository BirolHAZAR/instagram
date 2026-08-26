
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from core.views.main import sentry_test_view
from django.contrib import admin
from django.views.generic import RedirectView


# Özel admin site'yi kullan


urlpatterns = [
    path('admin/', admin.site.urls),
    #path('admin/', admin_site.urls), 
    path('', include('core.urls')),
    path('confirm-email/', RedirectView.as_view(pattern_name='account_email_verification_sent', permanent=False)),
    path('accounts/', include('allauth.urls')),  # Allauth URL'leri
    path('sentry-test/', sentry_test_view, name='sentry_test'),
    path("i18n/", include("django.conf.urls.i18n")),
]

# Geliştirme ortamında medya dosyalarını serve et
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)


handler400 = "core.views.main.bad_request_view"
handler403 = "core.views.main.permission_denied_view"
handler404 = "core.views.main.not_found_view"
handler500 = "core.views.main.server_error_view"
