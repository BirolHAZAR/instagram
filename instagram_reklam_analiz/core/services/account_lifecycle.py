from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from datetime import datetime, time, timedelta

from core.models import AccountDeletionRecord, UserProfile, UserSubscription


ACCOUNT_DELETION_GRACE_MONTHS = 3


def get_deletion_suspension_time(user, now=None):
    now = now or timezone.now()
    today = now.date()
    latest_end_date = (
        UserSubscription.objects.filter(user=user, is_active=True, end_date__gte=today)
        .order_by("-end_date")
        .values_list("end_date", flat=True)
        .first()
    )
    if not latest_end_date:
        return now

    suspend_date = latest_end_date + timedelta(days=1)
    suspend_at = datetime.combine(suspend_date, time.min)
    if timezone.is_naive(suspend_at):
        suspend_at = timezone.make_aware(suspend_at, timezone.get_current_timezone())
    return max(now, suspend_at)


def get_scheduled_deletion_time(suspends_at=None):
    suspends_at = suspends_at or timezone.now()
    return suspends_at + relativedelta(months=ACCOUNT_DELETION_GRACE_MONTHS)


def pending_deletion_suspended_filter(now=None):
    now = now or timezone.now()
    return Q(profile__pending_deletion=True) & (
        Q(profile__deletion_suspends_at__isnull=True) | Q(profile__deletion_suspends_at__lte=now)
    )


def _user_snapshot(user):
    return {
        "user": user,
        "username": getattr(user, "username", "") or "",
        "email": getattr(user, "email", "") or "",
        "full_name": user.get_full_name() if hasattr(user, "get_full_name") else "",
    }


def upsert_deletion_record(user, profile):
    now = timezone.now()
    status = (
        AccountDeletionRecord.STATUS_SCHEDULED
        if profile.deletion_suspends_at and profile.deletion_suspends_at > now
        else AccountDeletionRecord.STATUS_SUSPENDED
    )
    record = (
        AccountDeletionRecord.objects
        .filter(user=user)
        .exclude(status__in=[AccountDeletionRecord.STATUS_CANCELLED, AccountDeletionRecord.STATUS_DELETED])
        .order_by("-requested_at", "-id")
        .first()
    )
    if record is None:
        record = AccountDeletionRecord(requested_at=profile.deletion_requested_at or now)

    for field, value in _user_snapshot(user).items():
        setattr(record, field, value)
    record.status = status
    record.requested_at = profile.deletion_requested_at or now
    record.suspends_at = profile.deletion_suspends_at
    record.scheduled_deletion_at = profile.scheduled_deletion_at
    record.cancelled_at = None
    record.deleted_at = None
    record.note = (
        "Aktif abonelik bitimi bekleniyor."
        if status == AccountDeletionRecord.STATUS_SCHEDULED
        else "Hesap askida; 3 aylik geri donus suresi basladi."
    )
    record.save()
    return record


def active_user_queryset():
    User = get_user_model()
    return User.objects.filter(is_active=True).exclude(pending_deletion_suspended_filter())


def suspend_user_for_deletion(user):
    now = timezone.now()
    suspends_at = get_deletion_suspension_time(user, now)
    profile, _created = UserProfile.objects.get_or_create(user=user)
    profile.pending_deletion = True
    profile.deletion_requested_at = now
    profile.deletion_suspends_at = suspends_at
    profile.scheduled_deletion_at = get_scheduled_deletion_time(suspends_at)
    profile.deletion_cancelled_at = None
    profile.save(
        update_fields=[
            "pending_deletion",
            "deletion_requested_at",
            "deletion_suspends_at",
            "scheduled_deletion_at",
            "deletion_cancelled_at",
            "updated_at",
        ]
    )
    upsert_deletion_record(user, profile)
    return profile


def reactivate_user_if_within_grace_period(user):
    profile = getattr(user, "profile", None)
    if not profile or not profile.pending_deletion:
        return False

    now = timezone.now()
    if profile.deletion_suspends_at and profile.deletion_suspends_at > now:
        return False
    if profile.scheduled_deletion_at and profile.scheduled_deletion_at <= now:
        return False

    profile.pending_deletion = False
    profile.deletion_cancelled_at = now
    profile.save(update_fields=["pending_deletion", "deletion_cancelled_at", "updated_at"])
    AccountDeletionRecord.objects.filter(user=user).exclude(
        status__in=[AccountDeletionRecord.STATUS_CANCELLED, AccountDeletionRecord.STATUS_DELETED]
    ).update(status=AccountDeletionRecord.STATUS_CANCELLED, cancelled_at=now, note="Kullanici girisiyle silme talebi iptal edildi.")
    return True


def mark_due_deletion_records_suspended(now=None):
    now = now or timezone.now()
    return AccountDeletionRecord.objects.filter(
        status=AccountDeletionRecord.STATUS_SCHEDULED,
        suspends_at__isnull=False,
        suspends_at__lte=now,
    ).update(status=AccountDeletionRecord.STATUS_SUSPENDED, note="Abonelik suresi bitti; hesap askiya alindi.")


def mark_user_deletion_record_deleted(user, now=None):
    now = now or timezone.now()
    record = (
        AccountDeletionRecord.objects
        .filter(user=user)
        .exclude(status__in=[AccountDeletionRecord.STATUS_CANCELLED, AccountDeletionRecord.STATUS_DELETED])
        .order_by("-requested_at", "-id")
        .first()
    )
    if record is None:
        record = AccountDeletionRecord(requested_at=now)

    for field, value in _user_snapshot(user).items():
        setattr(record, field, value)
    record.status = AccountDeletionRecord.STATUS_DELETED
    record.deleted_at = now
    record.user = None
    record.note = "3 aylik askida kalma suresi doldu; kullanici ve iliskili veriler kalici silindi."
    record.save()
    return record


def expired_pending_deletion_users(now=None):
    now = now or timezone.now()
    return get_user_model().objects.filter(
        profile__pending_deletion=True,
        profile__scheduled_deletion_at__isnull=False,
        profile__scheduled_deletion_at__lte=now,
    )
