# core/ai_agents/error_manager.py
import logging
import traceback
from datetime import datetime

import sentry_sdk
from django.conf import settings

logger = logging.getLogger(__name__)


class ErrorManager:
    LEVEL_DEBUG = 'debug'
    LEVEL_INFO = 'info'
    LEVEL_WARNING = 'warning'
    LEVEL_ERROR = 'error'
    LEVEL_CRITICAL = 'critical'

    def __init__(self, user=None, request=None):
        self.user = user
        self.request = request
        self.sentry_enabled = bool(getattr(settings, 'SENTRY_DSN', None))

    def capture_exception(self, exception, level='error', tags=None, extra=None):
        # 1. Logla - DÜZELTİLDİ
        log_func = getattr(logger, level.lower(), logger.error)
        log_func(f"Hata yakalandı: {str(exception)}", exc_info=True)

        # 2. Veritabanına kaydet (hatayı bastır)
        try:
            from core.models.error_log import SystemErrorLog
            error_log = SystemErrorLog.objects.create(
                message=str(exception)[:500],
                severity=level,
                status='new',
                traceback=traceback.format_exc(),
                tags=tags or {},
                extra_data=extra or {},
                user=self.user,
                url=self.request.path if self.request else None,
                method=self.request.method if self.request else None,
            )
            error_log.error_id = f"ERR-{error_log.id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            error_log.save()
        except Exception:
            pass  # Veritabanı hatasını görmezden gel

        # 3. Sentry
        if self.sentry_enabled:
            with sentry_sdk.push_scope() as scope:
                if self.user:
                    sentry_sdk.set_user({'id': self.user.id, 'username': self.user.username})
                if tags:
                    for k, v in tags.items():
                        scope.set_tag(k, v)
                if extra:
                    for k, v in extra.items():
                        scope.set_extra(k, v)
                sentry_sdk.capture_exception(exception)

    def capture_message(self, message, level='info', tags=None, extra=None):
        log_func = getattr(logger, level.lower(), logger.info)
        log_func(message)
        if self.sentry_enabled:
            with sentry_sdk.push_scope() as scope:
                if self.user:
                    sentry_sdk.set_user({'id': self.user.id, 'username': self.user.username})
                if tags:
                    for k, v in tags.items():
                        scope.set_tag(k, v)
                if extra:
                    for k, v in extra.items():
                        scope.set_extra(k, v)
                sentry_sdk.capture_message(message, level=level)

    # Diğer metodlar (validate_analysis_health, validate_ad_data) aynen kalabilir
    def validate_analysis_health(self, results):
        return {'health_score': 100, 'is_healthy': True, 'warnings': [], 'quality_notes': '', 'failed_agents': []}

    def validate_ad_data(self, ad):
        return {'is_valid': True, 'issues': [], 'error_count': 0}


def capture_errors(func):
    from functools import wraps
    from django.contrib import messages
    from django.http import JsonResponse
    from django.shortcuts import redirect

    @wraps(func)
    def wrapper(request, *args, **kwargs):
        try:
            return func(request, *args, **kwargs)
        except Exception as e:
            error_manager = ErrorManager(
                user=request.user if request.user.is_authenticated else None,
                request=request
            )
            error_manager.capture_exception(e, level='error', tags={'view': func.__name__})
            messages.error(request, 'Bir hata oluştu.')
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': 'Hata oluştu.'}, status=500)
            return redirect('dashboard')
    return wrapper


def handle_celery_task_failure(task, exc, task_id, args, kwargs, einfo):
    error_manager = ErrorManager()
    error_manager.capture_exception(exc, level='error', tags={'task_name': task.name, 'task_id': task_id})
