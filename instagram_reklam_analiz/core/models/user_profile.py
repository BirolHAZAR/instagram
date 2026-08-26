from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    LANGUAGE_CHOICES = [
        ("tr", "Türkçe"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    preferred_language = models.CharField(
        max_length=5,
        choices=LANGUAGE_CHOICES,
        default="tr",
    )

    allow_concurrent_sessions = models.BooleanField(
        default=False,
        verbose_name="Eşzamanlı oturumlara izin ver",
        help_text="Açık olduğunda kullanıcı aynı anda birden fazla tarayıcıda çalışabilir.",
    )
    active_session_key = models.CharField(
        max_length=40,
        blank=True,
        editable=False,
        verbose_name="Aktif oturum anahtarı",
    )
    active_session_last_seen = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name="Aktif oturum son kullanım",
    )

    pending_deletion = models.BooleanField(default=False, db_index=True)
    deletion_requested_at = models.DateTimeField(null=True, blank=True)
    deletion_suspends_at = models.DateTimeField(null=True, blank=True, db_index=True)
    scheduled_deletion_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deletion_cancelled_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Kullanıcı Profili"
        verbose_name_plural = "Kullanıcı Profilleri"

    def __str__(self):
        return f"{self.user} - {self.preferred_language}"


class AccountDeletionRecord(models.Model):
    STATUS_REQUESTED = "requested"
    STATUS_SCHEDULED = "scheduled"
    STATUS_SUSPENDED = "suspended"
    STATUS_CANCELLED = "cancelled"
    STATUS_DELETED = "deleted"

    STATUS_CHOICES = [
        (STATUS_REQUESTED, "Talep alindi"),
        (STATUS_SCHEDULED, "Abonelik bitimi bekleniyor"),
        (STATUS_SUSPENDED, "Askida"),
        (STATUS_CANCELLED, "Iptal edildi"),
        (STATUS_DELETED, "Kalici silindi"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deletion_records",
    )
    username = models.CharField(max_length=150, blank=True, db_index=True)
    email = models.EmailField(blank=True, db_index=True)
    full_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_REQUESTED, db_index=True)
    requested_at = models.DateTimeField()
    suspends_at = models.DateTimeField(null=True, blank=True, db_index=True)
    scheduled_deletion_at = models.DateTimeField(null=True, blank=True, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hesap Silme Kaydi"
        verbose_name_plural = "Hesap Silme Kayitlari"
        ordering = ["-requested_at", "-id"]
        indexes = [
            models.Index(fields=["status", "scheduled_deletion_at"], name="core_accoun_status_43ca48_idx"),
            models.Index(fields=["email", "status"], name="core_accoun_email_d68a73_idx"),
        ]

    def __str__(self):
        return f"{self.email or self.username or self.user_id} - {self.get_status_display()}"


class SuspendedAccountDeletionRecord(AccountDeletionRecord):
    class Meta:
        proxy = True
        verbose_name = "Askıya Alınmış Üye"
        verbose_name_plural = "Askıya Alınmış Üyeler"


class DeletedAccountDeletionRecord(AccountDeletionRecord):
    class Meta:
        proxy = True
        verbose_name = "Silinmiş Üye"
        verbose_name_plural = "Silinmiş Üyeler"
