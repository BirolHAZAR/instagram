from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.apps import apps
from django.utils import timezone
from django.db.models import Sum
from django.http import HttpResponseForbidden
from datetime import datetime, time


def _model(name):
    try:
        return apps.get_model("core", name)
    except LookupError:
        return None


def _field(model, *names):
    if not model:
        return None
    model_fields = {f.name for f in model._meta.get_fields()}
    for name in names:
        if name in model_fields:
            return name
    return None


def _safe_count(model, filters=None):
    if not model:
        return 0
    try:
        qs = model.objects.all()
        if filters:
            qs = qs.filter(**filters)
        return qs.count()
    except Exception:
        return 0


def _safe_sum(model, field_name, filters=None):
    if not model or not field_name:
        return 0
    try:
        qs = model.objects.all()
        if filters:
            qs = qs.filter(**filters)
        return qs.aggregate(total=Sum(field_name)).get("total") or 0
    except Exception:
        return 0


def _to_aware(value):
    if not value:
        return None

    try:
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return timezone.localtime(value)
    except Exception:
        return None


def _time_ago_label(value):
    value = _to_aware(value)
    if not value:
        return "Henüz senkron yok"

    now = timezone.localtime(timezone.now())

    try:
        diff = now - value
    except Exception:
        return "Henüz senkron yok"

    seconds = int(diff.total_seconds())

    if seconds < 0:
        return value.strftime("%d.%m.%Y %H:%M")

    if seconds < 60:
        return "az önce"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} dk önce"

    hours = minutes // 60
    if hours < 24:
        return f"{hours} saat önce"

    days = hours // 24
    if days < 7:
        return f"{days} gün önce"

    return value.strftime("%d.%m.%Y %H:%M")


def _date_range_filter(field_name, day):
    """
    __date filtresi yerine aware datetime aralığı kullanır.
    Bu, naive datetime localtime hatasını engeller.
    """
    if not field_name:
        return None

    if field_name in ["date", "metric_date"]:
        return {field_name: day}

    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    end = timezone.make_aware(datetime.combine(day, time.max), tz)

    return {
        f"{field_name}__gte": start,
        f"{field_name}__lte": end,
    }


@login_required
def sync_center(request):
    if not (request.user.is_staff or request.user.is_superuser):
        return HttpResponseForbidden("Bu ekran yalnızca teknik yöneticiler içindir.")

    Platform = _model("Platform")
    PlatformConnection = _model("PlatformConnection")
    PlatformAccount = _model("PlatformAccount")
    PlatformSyncJob = _model("PlatformSyncJob")
    Campaign = _model("Campaign")
    AdGroup = _model("AdGroup")
    Ad = _model("Ad")
    Creative = _model("Creative")
    AdMetricHistory = _model("AdMetricHistory")

    today = timezone.localdate()

    user_filter = {}
    if PlatformAccount and _field(PlatformAccount, "user"):
        user_filter["user"] = request.user

    platforms = []
    platform_qs = Platform.objects.all().order_by("name") if Platform else []

    for platform in platform_qs:
        code = getattr(platform, "code", "") or getattr(platform, "slug", "") or getattr(platform, "name", "")
        name = getattr(platform, "name", code)

        connection = None
        account_count = 0

        if PlatformConnection:
            try:
                conn_filters = {}
                if _field(PlatformConnection, "user"):
                    conn_filters["user"] = request.user
                if _field(PlatformConnection, "platform"):
                    conn_filters["platform"] = platform
                connection = PlatformConnection.objects.filter(**conn_filters).order_by("-id").first()
            except Exception:
                connection = None

        if PlatformAccount:
            try:
                acc_filters = {}
                if _field(PlatformAccount, "user"):
                    acc_filters["user"] = request.user
                if _field(PlatformAccount, "platform"):
                    acc_filters["platform"] = platform
                elif _field(PlatformAccount, "connection") and connection:
                    acc_filters["connection"] = connection
                account_count = PlatformAccount.objects.filter(**acc_filters).count()
            except Exception:
                account_count = 0

        last_job = None
        if PlatformSyncJob:
            try:
                job_filters = {}
                if _field(PlatformSyncJob, "user"):
                    job_filters["user"] = request.user
                if _field(PlatformSyncJob, "platform"):
                    job_filters["platform"] = platform
                elif _field(PlatformSyncJob, "connection") and connection:
                    job_filters["connection"] = connection
                last_job = PlatformSyncJob.objects.filter(**job_filters).order_by("-id").first()
            except Exception:
                last_job = None

        status = "empty"
        status_label = "Bağlantı yok"
        last_sync_label = "Henüz senkron yok"
        error_message = ""

        if connection or account_count:
            status = "ok"
            status_label = "Hazır"

        if last_job:
            raw_status = (getattr(last_job, "status", "") or "").lower()
            error_message = getattr(last_job, "error_message", "") or getattr(last_job, "error", "") or ""

            last_sync_value = (
                getattr(last_job, "finished_at", None)
                or getattr(last_job, "completed_at", None)
                or getattr(last_job, "updated_at", None)
                or getattr(last_job, "created_at", None)
            )

            last_sync_label = _time_ago_label(last_sync_value)

            if raw_status in ["failed", "error"]:
                status = "error"
                status_label = "Hata"
            elif raw_status in ["running", "processing", "started", "pending"]:
                status = "running"
                status_label = "İşleniyor"
            elif raw_status in ["completed", "success", "done"]:
                status = "ok"
                status_label = "Senkron tamam"

        platforms.append({
            "code": code,
            "name": name,
            "account_count": account_count,
            "status": status,
            "status_label": status_label,
            "last_sync_label": last_sync_label,
            "error_message": error_message,
        })

    created_field_campaign = _field(Campaign, "created_at", "created_time")
    created_field_adgroup = _field(AdGroup, "created_at", "created_time")
    created_field_ad = _field(Ad, "created_at", "created_time")
    created_field_creative = _field(Creative, "created_at", "created_time")
    date_field_metric = _field(AdMetricHistory, "date", "metric_date", "created_at", "created_time")

    context = {
        "platforms": platforms,
        "today_campaigns": _safe_count(Campaign, _date_range_filter(created_field_campaign, today)),
        "today_adgroups": _safe_count(AdGroup, _date_range_filter(created_field_adgroup, today)),
        "today_ads": _safe_count(Ad, _date_range_filter(created_field_ad, today)),
        "today_creatives": _safe_count(Creative, _date_range_filter(created_field_creative, today)),
        "today_metrics": _safe_count(AdMetricHistory, _date_range_filter(date_field_metric, today)),
        "total_accounts": _safe_count(PlatformAccount, user_filter),
        "total_campaigns": _safe_count(Campaign),
        "total_ads": _safe_count(Ad),
        "total_metrics": _safe_count(AdMetricHistory),
    }

    return render(request, "reports/sync_center.html", context)
