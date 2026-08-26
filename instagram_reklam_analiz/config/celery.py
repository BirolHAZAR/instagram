# config/celery.py
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("instagram_reklam_analiz")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


def celery_failure_handler(task, exc, task_id, args, kwargs, einfo):
    """Capture Celery task failures without coupling Django settings to Celery."""
    from core.ai_agents.error_manager import ErrorManager

    error_manager = ErrorManager()
    error_manager.capture_exception(
        exc,
        level=ErrorManager.LEVEL_ERROR,
        tags={
            "celery_task": task.name,
            "task_id": task_id,
        },
        extra={
            "args": str(args),
            "kwargs": str(kwargs),
        },
    )


app.conf.task_failure_handler = celery_failure_handler

# Control Tower AI task modülü Celery worker tarafından kesin kayıt edilsin.
# Bu satır, "Received unregistered task" hatasını engellemek için bilerek bırakıldı.
try:
    import core.tasks.control_tower_ai  # noqa: F401
except Exception:
    pass


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
