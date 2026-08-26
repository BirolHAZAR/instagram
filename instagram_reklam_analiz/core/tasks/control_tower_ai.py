from __future__ import annotations

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.services.control_tower_snapshot import build_lightweight_snapshot_for_user


@shared_task(bind=True, name="core.tasks.control_tower_ai.generate_control_tower_ai_report_task")
def generate_control_tower_ai_report_task(self, user_id: int, period: str = "monthly", days: int = 30, force: bool = True):
    """Control Tower Octo AI analiz raporunu arka planda üretir.

    HTTP request'i bekletmez. Dashboard butonu bu task'ı kuyruğa atar,
    frontend ise task durumunu polling ile takip eder.
    """
    User = get_user_model()
    user = User.objects.get(id=user_id)
    days = max(1, min(int(days or 30), 365))
    period = period or "monthly"

    self.update_state(state="PROGRESS", meta={"step": "snapshot", "progress": 25})
    snapshot = build_lightweight_snapshot_for_user(user, period=period, days=days)

    self.update_state(state="PROGRESS", meta={"step": "analysis", "progress": 75})
    return {
        "snapshot_id": snapshot.id,
        "period": period,
        "days": days,
        "created_at": timezone.localtime(snapshot.created_at).strftime("%d.%m.%Y %H:%M"),
    }
