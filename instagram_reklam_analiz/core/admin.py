import csv
import re
from datetime import timedelta
from io import StringIO
from decimal import Decimal
from urllib.parse import urlencode

from django.apps import apps
from django.conf import settings
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model, logout as auth_logout
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.csrf import csrf_exempt
from core.services.entitlements import (
    get_active_subscription,
    get_ai_credit_balance,
    get_saas_ai_credit_cycle,
    get_subscription_credit_cycle,
)
from core.models import RawDataSnapshot
from core.models import (
    Platform, PlatformAccount, PlatformConnection, PlatformSyncJob, UserProfile,
    AccountDeletionRecord, SuspendedAccountDeletionRecord, DeletedAccountDeletionRecord,
    Campaign, AdGroup, Creative, Ad,
    CampaignMetricHistory, AdGroupMetricHistory, AdMetricHistory, CreativeMetricHistory,
    CreativeTemplate, CreativeProject, GeneratedContent,
    BudgetOptimizationRule, BudgetOptimizationLog,
    AnomalyAlert, OpportunityWindow, Notification, NotificationPreference, ActivityLog,
    RawPlatformData, OctoScoreHistory, AIRecommendationHistory,
    MembershipPlan, PlanAuthorizationPolicy, UserSubscription, ReferralCode, ReferralProgramSetting, ReferralProgramRule, ReferralReward, Organization, OrganizationMember, AgencyRoleGroup, AgencyClient,
    PaymentMethod, AICreditPackage, AIOperationTariff, AICreditLedger, UserAICreditBalance, FeatureUsageLedger,
    ProductResearchPackage, ProductResearchLedger, UserProductResearchBalance,
    SaaSAICreditPool, OpenAITokenUsageLedger, TavilyAPIPool, TavilyAPIUsageLedger,
    Marketplace, MarketplaceAccount, MarketplaceSyncRun, Product, ProductVariant, MarketplaceListing,
    MarketplaceListingMetricHistory, MarketplaceProductChangeHistory, MarketplaceProductResearch,
    MarketplaceProductResearchMetricHistory,
    MarketplaceProductResearchResult,
    SocialPost, SocialPostMetricHistory,
    Influencer, InfluencerMetricHistory,
    CampaignOctoAnalysis, CampaignOctoRecommendation,
    ContactMessage, DemoRequest, Competitor, OctoTaskRule, OctoTaskInstance, OctoTaskActionLog, OctoRuleEngineRun,
    BillingInfo, Invoice, Payment, PaymentTransaction,
    InstagramAccount, InstagramMedia, InstagramInsight, InstagramPostQueue,
    AdCampaign, AdMetric, AIAnalysis, ReklamAIAnaliz, Report,
    SystemErrorLog, ControlTowerSnapshot, ControlTowerCardSnapshot, ControlTowerAIAnalysis,
    ControlTowerActionItem, ControlTowerDecision, AudienceHistory, PlacementHistory,
    AdminManagedCelerySchedule,
    LifecycleEmailCampaign, LifecycleEmailDelivery, Announcement, AnnouncementDelivery,
    LegalAcceptance, LegalDocument, LegalSiteSettings,
    SiteMaintenance,
)


@admin.register(SiteMaintenance)
class SiteMaintenanceAdmin(admin.ModelAdmin):
    list_display = ("status_badge", "title", "estimated_end_at", "updated_by", "updated_at")
    readonly_fields = ("updated_by", "updated_at")
    save_on_top = True
    fieldsets = (
        ("Bakım durumu", {"fields": ("is_active",)}),
        ("Ziyaretçiye gösterilecek içerik", {"fields": ("title", "message", "estimated_end_at", "contact_email")}),
        ("Kayıt bilgisi", {"fields": ("updated_by", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Durum", ordering="is_active")
    def status_badge(self, obj):
        color = "#15803d" if obj.is_active else "#64748b"
        label = "AKTİF — Site bakımda" if obj.is_active else "Kapalı"
        return format_html('<strong style="color:{}">{}</strong>', color, label)

    def has_add_permission(self, request):
        return not SiteMaintenance.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


class LegalDocumentAdminForm(forms.ModelForm):
    class Meta:
        model = LegalDocument
        fields = "__all__"
        widgets = {
            "summary": forms.Textarea(attrs={"rows": 3}),
            "content": forms.Textarea(attrs={"rows": 34, "style": "font-family: ui-monospace, Consolas, monospace;"}),
        }


@admin.register(LegalDocument)
class LegalDocumentAdmin(admin.ModelAdmin):
    form = LegalDocumentAdminForm
    list_display = ("title", "category", "status_badge", "version", "effective_date", "published_at", "updated_at")
    list_filter = ("status", "category", "requires_acceptance")
    search_fields = ("title", "summary", "content", "slug")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("published_at", "updated_by", "created_at", "updated_at", "preview_link")
    ordering = ("display_order", "title")
    actions = ("publish_selected", "unpublish_selected", "archive_selected")
    fieldsets = (
        ("Belge", {"fields": ("title", "slug", "category", "summary", "content")}),
        ("Yayın", {"fields": ("status", "version", "effective_date", "display_order", "requires_acceptance", "preview_link")}),
        ("Kayıt", {"fields": ("published_at", "updated_by", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def view_on_site(self, obj):
        return obj.get_absolute_url()

    @admin.display(description="Durum", ordering="status")
    def status_badge(self, obj):
        colors = {"draft": "#a16207", "published": "#15803d", "archived": "#64748b"}
        return format_html(
            '<span style="color:{};font-weight:800">{}</span>',
            colors.get(obj.status, "#334155"),
            obj.get_status_display(),
        )

    @admin.display(description="Site önizlemesi")
    def preview_link(self, obj):
        if not obj.pk:
            return "Belgeyi kaydettikten sonra önizleyebilirsiniz."
        return format_html('<a href="{}" target="_blank" rel="noopener">Metni sitede önizle</a>', obj.get_absolute_url())

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        if obj.status == LegalDocument.STATUS_PUBLISHED and not obj.published_at:
            obj.published_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.action(description="Seçili metinleri şimdi yayınla")
    def publish_selected(self, request, queryset):
        for document in queryset:
            document.publish(request.user)
        self.message_user(request, f"{queryset.count()} hukuki metin yayınlandı.", messages.SUCCESS)

    @admin.action(description="Seçili metinleri yayından kaldır ve taslağa al")
    def unpublish_selected(self, request, queryset):
        for document in queryset:
            document.unpublish(request.user)
        self.message_user(request, f"{queryset.count()} hukuki metin taslağa alındı.", messages.SUCCESS)

    @admin.action(description="Seçili metinleri arşivle")
    def archive_selected(self, request, queryset):
        updated = queryset.update(status=LegalDocument.STATUS_ARCHIVED, updated_by=request.user)
        self.message_user(request, f"{updated} hukuki metin arşivlendi.", messages.SUCCESS)


@admin.register(LegalSiteSettings)
class LegalSiteSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Şirket", {"fields": ("company_name", "brand_name", "address")}),
        ("Resmi bilgiler", {"fields": ("tax_office", "tax_number", "mersis_number", "kep_address")}),
        ("İletişim", {"fields": ("support_email", "kvkk_email", "phone")}),
        ("Hizmet seviyesi", {"fields": ("sla_target",)}),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not LegalSiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LegalAcceptance)
class LegalAcceptanceAdmin(admin.ModelAdmin):
    list_display = ("payment", "user", "accepted_at", "immediate_service_consent", "email_recipient", "email_sent_at")
    list_filter = ("immediate_service_consent", "email_sent_at", "accepted_at")
    search_fields = ("user__email", "user__username", "payment__id", "email_recipient", "ip_address")
    readonly_fields = (
        "user", "payment", "acceptance_statement", "immediate_service_consent", "ip_address", "user_agent",
        "accepted_at", "email_recipient", "email_sent_at", "email_error", "document_snapshots",
    )
    fieldsets = (
        ("Onay", {"fields": ("user", "payment", "accepted_at", "acceptance_statement", "immediate_service_consent")}),
        ("Kanıt", {"fields": ("ip_address", "user_agent", "document_snapshots")}),
        ("E-posta", {"fields": ("email_recipient", "email_sent_at", "email_error")}),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LifecycleEmailCampaign)
class LifecycleEmailCampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "delay_days", "repeat_days", "max_sends", "is_active", "delivery_count", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "subject", "body")
    readonly_fields = ("created_at", "updated_at")
    actions = ("send_due_now",)
    fieldsets = (
        ("Kampanya", {"fields": ("name", "is_active")}),
        ("E-posta İçeriği", {"fields": ("subject", "body", "cta_text", "cta_url")}),
        ("Tasarım", {"fields": ("html_template",), "description": "Boş bırakırsanız sistemdeki profesyonel logolu şablon kullanılır."}),
        ("Gönderim Kuralı", {"fields": ("delay_days", "repeat_days", "max_sends")}),
        ("Kayıt", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Gönderim")
    def delivery_count(self, obj):
        return obj.deliveries.filter(status="sent").count()

    @admin.action(description="Seçili kampanyalar için vadesi gelen e-postaları şimdi gönder")
    def send_due_now(self, request, queryset):
        from core.tasks.communications import dispatch_lifecycle_emails
        queryset.update(is_active=True)
        dispatch_lifecycle_emails.delay()
        self.message_user(request, "E-posta gönderim görevi kuyruğa alındı.", messages.SUCCESS)


@admin.register(LifecycleEmailDelivery)
class LifecycleEmailDeliveryAdmin(admin.ModelAdmin):
    list_display = ("campaign", "user", "sequence", "status", "sent_at")
    list_filter = ("status", "campaign")
    search_fields = ("user__email", "campaign__name", "error")
    readonly_fields = ("campaign", "user", "sequence", "status", "error", "sent_at")


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "publish_at", "send_in_app", "send_email", "is_active", "processed_at", "delivery_count")
    list_filter = ("is_active", "send_in_app", "send_email")
    search_fields = ("title", "message")
    readonly_fields = ("processed_at", "created_at", "updated_at")
    actions = ("publish_now", "reset_and_publish_again")
    fieldsets = (
        ("Duyuru", {"fields": ("title", "message", "link")}),
        ("E-posta Tasarımı", {"fields": ("html_template",), "description": "Boş bırakırsanız profesyonel logolu duyuru şablonu kullanılır."}),
        ("Yayın Ayarları", {"fields": ("publish_at", "expires_at", "send_in_app", "send_email", "is_active")}),
        ("Durum", {"fields": ("processed_at", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Teslimat")
    def delivery_count(self, obj):
        return obj.deliveries.count()

    @admin.action(description="Seçili duyuruları şimdi yayınla")
    def publish_now(self, request, queryset):
        from core.tasks.communications import dispatch_announcements
        queryset.update(is_active=True, publish_at=timezone.now(), processed_at=None)
        dispatch_announcements.delay()
        self.message_user(request, "Duyurular yayın kuyruğuna alındı.", messages.SUCCESS)

    @admin.action(description="Seçili duyuruları yeniden yayınla")
    def reset_and_publish_again(self, request, queryset):
        from core.tasks.communications import dispatch_announcements
        AnnouncementDelivery.objects.filter(announcement__in=queryset).delete()
        queryset.update(is_active=True, publish_at=timezone.now(), processed_at=None)
        dispatch_announcements.delay()
        self.message_user(request, "Duyurular yeniden yayın kuyruğuna alındı.", messages.SUCCESS)


@admin.register(AnnouncementDelivery)
class AnnouncementDeliveryAdmin(admin.ModelAdmin):
    list_display = ("announcement", "user", "notification_created", "email_sent", "created_at")
    list_filter = ("notification_created", "email_sent", "announcement")
    search_fields = ("user__email", "announcement__title", "error")
    readonly_fields = ("announcement", "user", "notification_created", "email_sent", "error", "created_at")


admin.site.site_header = "reklamanaliz.net SaaS Admin Paneli"
admin.site.site_title = "reklamanaliz.net Admin"
admin.site.index_title = "Yonetim ve Raporlama Merkezi"
admin.site.index_template = "admin/index.html"
admin.site.logout_template = "admin/logged_out.html"


def export_selected_as_csv(modeladmin, request, queryset):
    opts = modeladmin.model._meta
    sensitive_markers = ("password", "token", "secret", "api_key", "access_key", "refresh")
    fields = [
        field
        for field in opts.fields
        if not field.many_to_many and not field.one_to_many
        and not any(marker in field.name.lower() for marker in sensitive_markers)
    ]
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = f'attachment; filename="{opts.app_label}_{opts.model_name}_export.csv"'
    response.write("\ufeff")

    writer = csv.writer(response)
    writer.writerow([field.verbose_name or field.name for field in fields])
    for obj in queryset:
        row = []
        for field in fields:
            value = getattr(obj, field.name)
            if hasattr(value, "isoformat"):
                value = value.isoformat(sep=" ")
            row.append(value)
        writer.writerow(row)
    return response


export_selected_as_csv.short_description = "Secili kayitlari CSV olarak indir"
admin.site.add_action(export_selected_as_csv)


def mark_selected_active(modeladmin, request, queryset):
    if not _has_field(modeladmin.model, "is_active"):
        modeladmin.message_user(request, "Bu modelde is_active alani yok.", messages.WARNING)
        return
    updated = queryset.update(is_active=True)
    modeladmin.message_user(request, f"{updated} kayit aktif yapildi.", messages.SUCCESS)


mark_selected_active.short_description = "Secili kayitlari aktif yap"
admin.site.add_action(mark_selected_active)


def mark_selected_inactive(modeladmin, request, queryset):
    if not _has_field(modeladmin.model, "is_active"):
        modeladmin.message_user(request, "Bu modelde is_active alani yok.", messages.WARNING)
        return
    updated = queryset.update(is_active=False)
    modeladmin.message_user(request, f"{updated} kayit pasif yapildi.", messages.SUCCESS)


mark_selected_inactive.short_description = "Secili kayitlari pasif yap"
admin.site.add_action(mark_selected_inactive)


def mark_notifications_read(modeladmin, request, queryset):
    if not _has_field(modeladmin.model, "is_read"):
        modeladmin.message_user(request, "Bu modelde is_read alani yok.", messages.WARNING)
        return
    updated = queryset.update(is_read=True)
    modeladmin.message_user(request, f"{updated} bildirim okundu yapildi.", messages.SUCCESS)


mark_notifications_read.short_description = "Secili bildirimleri okundu yap"
admin.site.add_action(mark_notifications_read)


def resolve_system_errors(modeladmin, request, queryset):
    if not _has_field(modeladmin.model, "status"):
        modeladmin.message_user(request, "Bu modelde status alani yok.", messages.WARNING)
        return
    update_kwargs = {"status": "resolved"}
    if _has_field(modeladmin.model, "resolved_by"):
        update_kwargs["resolved_by"] = request.user
    if _has_field(modeladmin.model, "resolved_at"):
        update_kwargs["resolved_at"] = timezone.now()
    updated = queryset.update(**update_kwargs)
    modeladmin.message_user(request, f"{updated} kayit cozuldu olarak isaretlendi.", messages.SUCCESS)


resolve_system_errors.short_description = "Secili hata kayitlarini cozuldu yap"
admin.site.add_action(resolve_system_errors)


def queue_platform_account_sync(modeladmin, request, queryset):
    from core.models import PlatformSyncJob
    from core.tasks.ads_pipeline import sync_platform_account_ads

    queued = 0
    for account in queryset.filter(is_active=True).select_related("user"):
        job = PlatformSyncJob.objects.create(
            user=account.user,
            platform_account=account,
            days_back=365,
            status="pending",
            progress=0,
            message=f"Admin tarafindan senkron kuyruğuna alindi: {request.user}",
        )
        sync_platform_account_ads.delay(job.id)
        queued += 1
    modeladmin.message_user(request, f"{queued} platform hesabi senkron kuyruğuna alindi.", messages.SUCCESS)


queue_platform_account_sync.short_description = "Secili platform hesaplarini arka planda senkronize et"


def queue_octo_task_generation(modeladmin, request, queryset):
    from core.tasks.admin_ops import generate_octo_tasks

    async_result = generate_octo_tasks.delay()
    modeladmin.message_user(
        request,
        f"Octo gorev uretimi arka plana alindi. Celery task id: {async_result.id}",
        messages.SUCCESS,
    )


queue_octo_task_generation.short_description = "Octo gorevlerini arka planda yeniden uret"


def queue_token_refresh(modeladmin, request, queryset):
    from core.tasks.admin_ops import refresh_expired_tokens

    async_result = refresh_expired_tokens.delay()
    modeladmin.message_user(
        request,
        f"Token bakim gorevi arka plana alindi. Celery task id: {async_result.id}",
        messages.SUCCESS,
    )


queue_token_refresh.short_description = "Suresi dolan tokenlari arka planda kontrol et"


def run_admin_managed_schedule_now(modeladmin, request, queryset):
    from config.celery import app

    queued = 0
    for schedule in queryset:
        async_result = app.send_task(schedule.task_name, args=schedule.args or [], kwargs=schedule.kwargs or {})
        schedule.last_task_id = async_result.id
        schedule.last_run_at = timezone.now()
        schedule.last_error = ""
        schedule.save(update_fields=["last_task_id", "last_run_at", "last_error", "updated_at"])
        queued += 1
    modeladmin.message_user(request, f"{queued} görev kuyruğa alındı.", messages.SUCCESS)


run_admin_managed_schedule_now.short_description = "Seçili görevleri şimdi çalıştır"


def mark_octo_tasks_done(modeladmin, request, queryset):
    updated = queryset.update(status="done", completed_at=timezone.now())
    for task in queryset[:100]:
        OctoTaskActionLog.objects.create(task=task, user=request.user, action="done", note="Admin panelinden tamamlandi.")
    modeladmin.message_user(request, f"{updated} gorev tamamlandi olarak isaretlendi.", messages.SUCCESS)


mark_octo_tasks_done.short_description = "Secili gorevleri tamamlandi yap"


def dismiss_octo_tasks(modeladmin, request, queryset):
    updated = queryset.update(status="dismissed", dismissed_at=timezone.now())
    for task in queryset[:100]:
        OctoTaskActionLog.objects.create(task=task, user=request.user, action="dismissed", note="Admin panelinden kapatildi.")
    modeladmin.message_user(request, f"{updated} gorev kapatildi.", messages.SUCCESS)


dismiss_octo_tasks.short_description = "Secili gorevleri kapat"


def reopen_octo_tasks(modeladmin, request, queryset):
    updated = queryset.update(status="open", completed_at=None, dismissed_at=None, snoozed_until=None)
    for task in queryset[:100]:
        OctoTaskActionLog.objects.create(task=task, user=request.user, action="reopened", note="Admin panelinden tekrar acildi.")
    modeladmin.message_user(request, f"{updated} gorev tekrar acildi.", messages.SUCCESS)


reopen_octo_tasks.short_description = "Secili gorevleri tekrar ac"


def _has_field(model, field_name):
    return any(field.name == field_name for field in model._meta.fields)


def _currency(value):
    value = value or Decimal("0")
    return f"{value:,.2f} TL"


def _tr_decimal(value):
    try:
        number = Decimal(str(value or 0))
    except Exception:
        number = Decimal("0")
    formatted = f"{number:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _tr_int(value):
    try:
        number = int(Decimal(str(value or 0)))
    except Exception:
        number = 0
    return f"{number:,}".replace(",", ".")


STATUS_LABELS_TR = {
    "active": "Aktif",
    "connected": "Bağlı",
    "disconnected": "Bağlantı Kesildi",
    "expired": "Süresi Doldu",
    "error": "Hatalı",
    "completed": "Tamamlandı",
    "success": "Başarılı",
    "failed": "Başarısız",
    "running": "Çalışıyor",
    "pending": "Bekliyor",
    "queued": "Sırada",
    "skipped": "Atlandı",
    "watch": "İzleniyor",
    "warning": "Uyarı",
    "critical": "Kritik",
    "risky": "Riskli",
    "passive": "Pasif",
    "new": "Yeni",
    "investigating": "İnceleniyor",
    "resolved": "Çözüldü",
    "open": "Açık",
    "viewed": "Görüldü",
    "snoozed": "Ertelendi",
    "done": "Tamamlandı",
    "dismissed": "Kapatıldı",
    "draft": "Taslak",
    "paid": "Ödendi",
    "cancelled": "İptal Edildi",
    "rejected": "Reddedildi",
    "approved": "Onaylandı",
}


def _status_label_tr(obj, value):
    raw = str(value or "").strip()
    normalized = raw.lower()
    label = STATUS_LABELS_TR.get(normalized)
    if label:
        return label
    try:
        display = obj.get_status_display()
    except Exception:
        display = raw
    if display == raw:
        return raw.replace("_", " ").title()
    return display


def _credit_summary_for_ledger(queryset):
    loaded = 0
    used = 0
    latest_balance = 0
    latest_at = None
    for item in queryset.order_by("created_at", "id"):
        amount = int(item.amount or 0)
        if amount >= 0:
            loaded += amount
        else:
            used += abs(amount)
        latest_balance = int(item.balance_after or 0)
        latest_at = item.created_at
    return {
        "loaded": loaded,
        "used": used,
        "remaining": latest_balance if latest_at else loaded - used,
        "last_movement_at": latest_at,
    }


def _monthly_credit_summary(user, organization=None, subscription=None):
    subscription = subscription or get_active_subscription(user, organization=organization)
    cycle_start, cycle_end = get_subscription_credit_cycle(subscription)
    qs = AICreditLedger.objects.filter(
        user=user,
        created_at__date__gte=cycle_start,
        created_at__date__lt=cycle_end,
    )
    if organization is not None:
        qs = qs.filter(organization=organization)

    plan_limit = int(getattr(getattr(subscription, "plan", None), "ai_credits_per_month", 0) or 0)
    grants = sum(int(item.amount or 0) for item in qs.filter(action=AICreditLedger.ACTION_GRANT, amount__gt=0))
    topups = sum(
        int(item.amount or 0)
        for item in qs.filter(
            action__in=[
                AICreditLedger.ACTION_PURCHASE,
                AICreditLedger.ACTION_REFUND,
                AICreditLedger.ACTION_ADJUSTMENT,
            ],
            amount__gt=0,
        )
    )
    used = abs(sum(int(item.amount or 0) for item in qs.filter(action=AICreditLedger.ACTION_CONSUME, amount__lt=0)))
    loaded = max(plan_limit, grants) + topups
    return {
        "loaded": loaded,
        "used": used,
        "remaining": get_ai_credit_balance(user, organization=organization),
        "last_movement_at": qs.order_by("-created_at", "-id").values_list("created_at", flat=True).first(),
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
    }


def ai_credit_report_view(request):
    User = get_user_model()
    active_subscriptions = (
        UserSubscription.objects
        .filter(is_active=True, end_date__gte=timezone.localdate(), organization__isnull=True)
        .select_related("user", "plan", "organization")
        .order_by("user__email", "-start_date")
    )
    subscription_by_user = {}
    for subscription in active_subscriptions:
        subscription_by_user.setdefault(subscription.user_id, subscription)

    user_ids = set(subscription_by_user)
    user_ids.update(
        AICreditLedger.objects.filter(organization__isnull=True).values_list("user_id", flat=True).distinct()
    )

    user_rows = []
    for user in User.objects.filter(id__in=user_ids).order_by("email", "username"):
        subscription = subscription_by_user.get(user.id)
        summary = _monthly_credit_summary(user, subscription=subscription)
        plan = subscription.plan if subscription else None
        detail_url = reverse("admin:ai_credit_report_user", args=[user.id])
        user_rows.append({
            "name": user.get_full_name() or user.username or user.email,
            "email": user.email,
            "start_date": subscription.start_date if subscription else user.date_joined.date(),
            "plan": plan.display_name if plan else "-",
            "credit_limit": int(getattr(plan, "ai_credits_per_month", 0) or 0),
            "loaded": summary["loaded"],
            "used": summary["used"],
            "remaining": summary["remaining"],
            "last_movement_at": summary["last_movement_at"],
            "cycle_start": summary["cycle_start"],
            "cycle_end": summary["cycle_end"],
            "detail_url": detail_url,
        })

    organization_rows = []
    organizations = (
        Organization.objects
        .filter(is_active=True)
        .select_related("owner", "active_plan")
        .order_by("name")
    )
    org_ids_with_ledger = set(
        AICreditLedger.objects.exclude(organization=None).values_list("organization_id", flat=True).distinct()
    )
    for organization in organizations:
        org_ids_with_ledger.add(organization.id)

    for organization in Organization.objects.filter(id__in=org_ids_with_ledger).select_related("owner", "active_plan").order_by("name"):
        organization_subscription = get_active_subscription(organization.owner, organization=organization)
        plan = organization_subscription.plan if organization_subscription else organization.active_plan
        summary = _monthly_credit_summary(
            organization.owner, organization=organization, subscription=organization_subscription,
        )
        organization_rows.append({
            "name": organization.name,
            "owner": organization.owner.email or organization.owner.username,
            "start_date": organization.created_at.date(),
            "plan": plan.display_name if plan else "-",
            "credit_limit": int(getattr(plan, "ai_credits_per_month", 0) or 0),
            "loaded": summary["loaded"],
            "used": summary["used"],
            "remaining": summary["remaining"],
            "last_movement_at": summary["last_movement_at"],
            "cycle_start": summary["cycle_start"],
            "cycle_end": summary["cycle_end"],
            "detail_url": reverse("admin:ai_credit_report_organization", args=[organization.id]),
        })

    recent_usage = FeatureUsageLedger.objects.filter(created_at__gte=timezone.now() - timedelta(days=30))
    context = {
        **admin.site.each_context(request),
        "title": "AI Kontör Raporu",
        "saas_credit_pool": _latest_saas_credit_pool(),
        "user_rows": user_rows,
        "organization_rows": organization_rows,
        "user_totals": {
            "credit_limit": sum(row["credit_limit"] for row in user_rows),
            "loaded": sum(row["loaded"] for row in user_rows),
            "used": sum(row["used"] for row in user_rows),
            "remaining": sum(row["remaining"] for row in user_rows),
        },
        "organization_totals": {
            "credit_limit": sum(row["credit_limit"] for row in organization_rows),
            "loaded": sum(row["loaded"] for row in organization_rows),
            "used": sum(row["used"] for row in organization_rows),
            "remaining": sum(row["remaining"] for row in organization_rows),
        },
        "total_users": len(user_rows),
        "total_organizations": len(organization_rows),
        "total_loaded": sum(row["loaded"] for row in user_rows) + sum(row["loaded"] for row in organization_rows),
        "total_used": sum(row["used"] for row in user_rows) + sum(row["used"] for row in organization_rows),
        "total_remaining": sum(row["remaining"] for row in user_rows) + sum(row["remaining"] for row in organization_rows),
        "usage_success_count": recent_usage.filter(status=FeatureUsageLedger.STATUS_ALLOWED).count(),
        "usage_blocked_count": recent_usage.filter(status=FeatureUsageLedger.STATUS_BLOCKED).count(),
        "usage_failed_count": recent_usage.filter(status=FeatureUsageLedger.STATUS_FAILED).count(),
    }
    return TemplateResponse(request, "admin/ai_credit_report.html", context)


def _trial_report_rows(start_date, end_date):
    User = get_user_model()
    user_admin_url_name = f"admin:{User._meta.app_label}_{User._meta.model_name}_change"
    trial_ledgers = (
        AICreditLedger.objects
        .filter(
            action=AICreditLedger.ACTION_GRANT,
            amount__gt=0,
            reference__startswith="trial:",
            created_at__date__gte=start_date,
            created_at__date__lt=end_date,
        )
        .select_related("user", "subscription", "subscription__plan")
        .order_by("-created_at", "-id")
    )
    user_ids = list(trial_ledgers.values_list("user_id", flat=True).distinct())
    paid_subscription_by_user = {
        subscription.user_id: subscription
        for subscription in (
            UserSubscription.objects
            .filter(user_id__in=user_ids)
            .exclude(plan__name="trial_14")
            .select_related("plan", "organization")
            .order_by("user_id", "created_at")
        )
    }
    paid_payment_by_user = {
        payment.user_id: payment
        for payment in (
            Payment.objects
            .filter(user_id__in=user_ids, status="completed")
            .exclude(plan__name="trial_14")
            .select_related("plan")
            .order_by("user_id", "created_at")
        )
    }

    rows = []
    converted_rows = []
    seen_users = set()
    for ledger in trial_ledgers:
        if ledger.user_id in seen_users:
            continue
        seen_users.add(ledger.user_id)
        user = ledger.user
        trial_subscription = ledger.subscription
        paid_subscription = paid_subscription_by_user.get(user.id)
        paid_payment = paid_payment_by_user.get(user.id)
        converted = bool(paid_subscription or paid_payment)
        paid_plan = (
            getattr(getattr(paid_subscription, "plan", None), "display_name", "")
            or getattr(getattr(paid_payment, "plan", None), "display_name", "")
        )
        converted_at = (
            getattr(paid_payment, "created_at", None)
            or getattr(paid_subscription, "created_at", None)
        )
        row = {
            "user_id": user.id,
            "name": user.get_full_name() or user.username or user.email,
            "email": user.email,
            "joined_at": user.date_joined,
            "trial_started_at": ledger.created_at,
            "trial_start": getattr(trial_subscription, "start_date", None),
            "trial_end": getattr(trial_subscription, "end_date", None),
            "trial_credits": int(ledger.amount or 0),
            "converted": converted,
            "converted_at": converted_at,
            "paid_plan": paid_plan or "-",
            "detail_url": reverse(user_admin_url_name, args=[user.id]),
        }
        rows.append(row)
        if converted:
            converted_rows.append(row)
    return rows, converted_rows


def free_trial_report_view(request):
    today = timezone.localdate()
    week_start = today - timezone.timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    next_day = today + timezone.timedelta(days=1)

    weekly_rows, weekly_converted_rows = _trial_report_rows(week_start, next_day)
    monthly_rows, monthly_converted_rows = _trial_report_rows(month_start, next_day)
    context = {
        **admin.site.each_context(request),
        "title": "Ücretsiz Deneme Raporu",
        "trial_days": getattr(settings, "TRIAL_DAYS", 14),
        "trial_credits": getattr(settings, "TRIAL_AI_CREDITS", 50),
        "week_start": week_start,
        "week_end": today,
        "month_start": month_start,
        "month_end": today,
        "weekly_rows": weekly_rows,
        "weekly_converted_rows": weekly_converted_rows,
        "monthly_rows": monthly_rows,
        "monthly_converted_rows": monthly_converted_rows,
        "weekly_total": len(weekly_rows),
        "weekly_converted_total": len(weekly_converted_rows),
        "monthly_total": len(monthly_rows),
        "monthly_converted_total": len(monthly_converted_rows),
    }
    return TemplateResponse(request, "admin/free_trial_report.html", context)


def _latest_saas_credit_pool():
    today = timezone.localdate()
    cycle_start, cycle_end = get_saas_ai_credit_cycle(today)
    pool, _ = SaaSAICreditPool.objects.get_or_create(
        month=cycle_start,
        defaults={"purchased_credits": 1_000_000, "provider_name": "OpenAI"},
    )
    if pool.provider_name == "":
        pool.provider_name = "OpenAI"
        pool.save(update_fields=["provider_name", "updated_at"])
    return {
        "month": pool.month,
        "period_label": f"{cycle_start:%d.%m.%Y} - {cycle_end:%d.%m.%Y}",
        "purchased": pool.purchased_credits,
        "used": pool.used_credits,
        "remaining": pool.remaining_credits,
        "usage_percent": pool.usage_percent,
        "provider": pool.provider_name,
        "note": pool.note,
        "updated_at": pool.updated_at,
    }


def sync_openai_usage_admin_view(request):
    if request.method != "POST":
        return redirect("admin:index")

    output = StringIO()
    try:
        call_command("sync_openai_usage", stdout=output, no_color=True)
    except CommandError as exc:
        messages.error(request, f"OpenAI kullanım senkronu başarısız: {exc}")
    except Exception as exc:
        messages.error(request, f"OpenAI kullanım senkronunda beklenmeyen hata: {exc}")
    else:
        message = re.sub(r"\x1b\[[0-9;]*m", "", output.getvalue()).strip()
        message = message or "OpenAI kullanım verisi başarıyla yenilendi."
        messages.success(request, message)

    next_url = request.POST.get("next") or reverse("admin:index")
    return redirect(next_url)


def ai_credit_statement_view(request, scope, object_id):
    if scope == "user":
        User = get_user_model()
        subject = get_object_or_404(User, id=object_id)
        ledger_qs = AICreditLedger.objects.filter(user=subject)
        title = f"{subject.email or subject.username} kontör ekstresi"
        back_label = "Üye raporuna dön"
    else:
        subject = get_object_or_404(Organization, id=object_id)
        ledger_qs = AICreditLedger.objects.filter(organization=subject)
        title = f"{subject.name} kontör ekstresi"
        back_label = "Ajans raporuna dön"

    movements = list(
        ledger_qs
        .select_related("user", "organization", "subscription", "package")
        .order_by("-created_at", "-id")
    )
    summary = _credit_summary_for_ledger(ledger_qs)
    context = {
        **admin.site.each_context(request),
        "title": title,
        "subject": subject,
        "scope": scope,
        "back_label": back_label,
        "summary": summary,
        "movements": movements,
        "movement_total": sum(abs(int(item.amount or 0)) for item in movements),
    }
    return TemplateResponse(request, "admin/ai_credit_statement.html", context)


@csrf_exempt
def admin_logout_view(request):
    request.current_app = admin.site.name
    if request.user.is_authenticated:
        auth_logout(request)
    request.session.flush()
    context = {
        **admin.site.each_context(request),
        "has_permission": False,
    }
    response = TemplateResponse(request, "admin/logged_out.html", context)
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


def _schedule_to_text(schedule):
    return str(schedule)


def _human_crontab_value(value):
    return str(value or "*")


def _human_schedule(schedule):
    minute = _human_crontab_value(getattr(schedule, "_orig_minute", ""))
    hour = _human_crontab_value(getattr(schedule, "_orig_hour", ""))
    day_of_week = _human_crontab_value(getattr(schedule, "_orig_day_of_week", ""))
    day_of_month = _human_crontab_value(getattr(schedule, "_orig_day_of_month", ""))

    if minute == "*" and hour == "*" and day_of_week == "*" and day_of_month == "*":
        return "Her dakika"
    if minute.isdigit() and hour.startswith("*/"):
        return f"Her {hour[2:]} saatte bir, saatin {minute}. dakikasında"
    if minute.isdigit() and hour == "*/1":
        return f"Her saat, saatin {minute}. dakikasında"
    if minute.isdigit() and hour.isdigit() and day_of_month == "1":
        return f"Her ayın 1. günü saat {hour.zfill(2)}:{minute.zfill(2)}"
    if minute.isdigit() and hour.isdigit() and day_of_week != "*":
        days = {
            "0": "Pazar",
            "1": "Pazartesi",
            "2": "Salı",
            "3": "Çarşamba",
            "4": "Perşembe",
            "5": "Cuma",
            "6": "Cumartesi",
        }
        return f"Her {days.get(day_of_week, day_of_week)} saat {hour.zfill(2)}:{minute.zfill(2)}"
    if minute.isdigit() and hour.isdigit():
        return f"Her gün saat {hour.zfill(2)}:{minute.zfill(2)}"
    return _schedule_to_text(schedule)


TASK_DISPLAY_NAMES = {
    "core.tasks.notification_tasks.scan_critical_alerts_for_all_users": "Kritik uyarıları tara",
    "core.tasks.notification_tasks.refresh_all_users_alerts": "Kullanıcı uyarılarını yenile",
    "core.tasks.notification_tasks.send_daily_notification_summaries": "Günlük bildirim özetlerini gönder",
    "core.tasks.sync_tasks.sync_all_platform_accounts": "Tüm platform hesaplarını senkronize et",
    "core.tasks.metric_tasks.record_daily_metrics_for_all_ads": "Günlük reklam metriklerini kaydet",
    "core.tasks.metric_tasks.cleanup_old_metric_history": "Eski metrik geçmişini temizle",
    "core.tasks.maintenance_tasks.refresh_expired_tokens": "Süresi dolan tokenları yenile",
    "core.tasks.maintenance_tasks.cleanup_old_raw_data": "Eski ham verileri temizle",
    "core.tasks.maintenance_tasks.sync_account_deletion_lifecycle": "Hesap silme/askı yaşam döngüsünü işle",
    "core.tasks.maintenance_tasks.process_due_subscription_renewals": "Vadesi gelen abonelikleri otomatik yenile",
    "core.tasks.maintenance_tasks.purge_expired_pending_deletion_accounts": "Süresi dolan askıdaki hesapları kalıcı sil",
    "core.tasks.report_tasks.generate_weekly_report": "Haftalık rapor üret",
    "core.tasks.marketplace_sync.refresh_tracked_marketplace_researches": "Takip edilen pazar yeri araştırmalarını yenile",
    "core.tasks.admin_ops.dispatch_admin_managed_schedules": "Admin periyodik görevlerini kontrol et",
    "core.tasks.admin_ops.generate_octo_tasks": "Octo görevlerini üret",
    "core.tasks.admin_ops.refresh_expired_tokens": "Token bakım görevini çalıştır",
}


def _task_display_name(task_name):
    if not task_name:
        return "Bilinmeyen görev"
    if task_name in TASK_DISPLAY_NAMES:
        return TASK_DISPLAY_NAMES[task_name]
    short_name = task_name.rsplit(".", 1)[-1].replace("_", " ")
    translations = {
        "sync": "senkronize et",
        "cleanup": "temizle",
        "clean": "temizle",
        "refresh": "yenile",
        "generate": "üret",
        "record": "kaydet",
        "send": "gönder",
        "scan": "tara",
        "update": "güncelle",
        "import": "içe aktar",
        "export": "dışa aktar",
        "all": "tüm",
        "daily": "günlük",
        "weekly": "haftalık",
        "monthly": "aylık",
        "old": "eski",
        "expired": "süresi dolan",
        "tokens": "tokenlar",
        "accounts": "hesaplar",
        "metrics": "metrikler",
        "report": "rapor",
        "reports": "raporlar",
        "alerts": "uyarılar",
        "notifications": "bildirimler",
    }
    words = [translations.get(word, word) for word in short_name.split()]
    return " ".join(words).capitalize()


def _default_task_schedule_hint(task_name):
    if not task_name:
        return "İhtiyaca göre periyot seç."
    lowered = task_name.lower()
    if "daily" in lowered:
        return "Günde 1 kez çalıştırılabilir."
    if "weekly" in lowered:
        return "Haftada 1 kez çalıştırılabilir."
    if "monthly" in lowered:
        return "Ayda 1 kez çalıştırılabilir."
    if "sync" in lowered or "refresh" in lowered:
        return "Saatlik veya birkaç saatte bir çalıştırılabilir."
    if "cleanup" in lowered or "clean" in lowered:
        return "Günlük veya aylık bakım görevi olarak çalıştırılabilir."
    if "send" in lowered or "notification" in lowered:
        return "Bildirim kuralına göre günlük/saatlik çalıştırılabilir."
    if "generate" in lowered or "record" in lowered:
        return "Rapor/metrik ihtiyacına göre günlük veya saatlik çalıştırılabilir."
    return "Bu task otomatik zamanlanmış olmayabilir; parametre gerektiriyorsa admin görevi olarak args/kwargs ile tanımla."


def _managed_task_create_url(task_name):
    display_name = _task_display_name(task_name)
    query = urlencode({
        "name": display_name,
        "task_name": task_name,
        "interval_every": 60,
        "interval_period": "minutes",
        "description": f"{display_name} için admin panelinden oluşturulan periyodik görev.",
    })
    return reverse("admin:core_adminmanagedceleryschedule_add") + f"?{query}"


def celery_tasks_view(request):
    from config.celery import app

    beat_schedule = getattr(settings, "CELERY_BEAT_SCHEDULE", {})

    if request.method == "POST":
        managed_id = request.POST.get("managed_id", "").strip()
        schedule_name = request.POST.get("schedule_name", "").strip()
        task_name = request.POST.get("task_name", "").strip()
        try:
            if managed_id:
                schedule = get_object_or_404(AdminManagedCelerySchedule, id=managed_id)
                async_result = app.send_task(schedule.task_name, args=schedule.args or [], kwargs=schedule.kwargs or {})
                schedule.last_task_id = async_result.id
                schedule.last_run_at = timezone.now()
                schedule.last_error = ""
                schedule.save(update_fields=["last_task_id", "last_run_at", "last_error", "updated_at"])
                messages.success(request, f"{schedule.name} kuyruğa alındı. Task id: {async_result.id}")
            elif schedule_name and schedule_name in beat_schedule:
                item = beat_schedule[schedule_name]
                async_result = app.send_task(
                    item.get("task"),
                    args=item.get("args", []),
                    kwargs=item.get("kwargs", {}),
                    **item.get("options", {}),
                )
                messages.success(request, f"{schedule_name} kuyruğa alındı. Task id: {async_result.id}")
            elif task_name:
                async_result = app.send_task(task_name)
                messages.success(request, f"{task_name} kuyruğa alındı. Task id: {async_result.id}")
        except Exception as exc:
            messages.error(request, f"Görev kuyruğa alınamadı: {exc}")

    static_schedules = []
    for name, item in beat_schedule.items():
        static_schedules.append({
            "name": name,
            "display_name": _task_display_name(item.get("task")),
            "task": item.get("task"),
            "schedule": _schedule_to_text(item.get("schedule")),
            "schedule_human": _human_schedule(item.get("schedule")),
            "args": item.get("args", []),
            "kwargs": item.get("kwargs", {}),
            "options": item.get("options", {}),
        })

    managed_schedules = AdminManagedCelerySchedule.objects.order_by("name")
    managed_active_tasks = set(
        managed_schedules.filter(is_active=True).values_list("task_name", flat=True)
    )
    managed_inactive_tasks = set(
        managed_schedules.filter(is_active=False).values_list("task_name", flat=True)
    )
    static_scheduled_tasks = {
        item.get("task")
        for item in beat_schedule.values()
        if item.get("task")
    }

    worker_status = []
    try:
        inspector = app.control.inspect(timeout=0.8)
        ping = inspector.ping() or {}
        active = inspector.active() or {}
        reserved = inspector.reserved() or {}
        registered = inspector.registered() or {}
        for worker_name in sorted(set(ping) | set(active) | set(reserved) | set(registered)):
            worker_status.append({
                "name": worker_name,
                "online": worker_name in ping,
                "active_count": len(active.get(worker_name, [])),
                "reserved_count": len(reserved.get(worker_name, [])),
                "registered_count": len(registered.get(worker_name, [])),
            })
    except Exception as exc:
        worker_status = [{"name": "Worker sorgulanamadı", "online": False, "active_count": 0, "reserved_count": 0, "registered_count": 0, "error": str(exc)}]

    recent_results = []
    try:
        from django_celery_results.models import TaskResult
        recent_results = [
            {
                "task_name": result.task_name,
                "display_name": _task_display_name(result.task_name),
                "status": result.status,
                "task_id": result.task_id,
                "date_done": result.date_done,
                "result": result.result,
            }
            for result in TaskResult.objects.order_by("-date_done")[:25]
        ]
    except Exception:
        recent_results = []

    registered_tasks = [
        {
            "name": task,
            "display_name": _task_display_name(task),
            "schedule_hint": _default_task_schedule_hint(task),
            "is_static_scheduled": task in static_scheduled_tasks,
            "is_managed_active": task in managed_active_tasks,
            "is_managed_inactive": task in managed_inactive_tasks,
            "auto_status": (
                "Sistem tarafından otomatik çalışıyor"
                if task in static_scheduled_tasks
                else "Admin görevi olarak otomatik çalışıyor"
                if task in managed_active_tasks
                else "Admin görevi var ama pasif"
                if task in managed_inactive_tasks
                else "Otomatik çalışmıyor"
            ),
            "create_url": _managed_task_create_url(task),
        }
        for task in sorted(app.tasks.keys())
        if not task.startswith("celery.")
    ]

    context = {
        **admin.site.each_context(request),
        "title": "Celery Görev Yönetimi",
        "static_schedules": static_schedules,
        "managed_schedules": managed_schedules,
        "worker_status": worker_status,
        "recent_results": recent_results,
        "registered_tasks": registered_tasks,
        "registered_task_count": len(registered_tasks),
        "static_schedule_count": len(static_schedules),
        "managed_schedule_count": managed_schedules.count(),
        "managed_active_count": managed_schedules.filter(is_active=True).count(),
        "managed_inactive_count": managed_schedules.filter(is_active=False).count(),
        "managed_add_url": reverse("admin:core_adminmanagedceleryschedule_add"),
        "managed_list_url": reverse("admin:core_adminmanagedceleryschedule_changelist"),
    }
    return TemplateResponse(request, "admin/celery_tasks.html", context)


def auth_security_view(request):
    from allauth.account.models import EmailAddress
    from allauth.mfa.models import Authenticator
    from core.services.social_auth_config import provider_rows

    User = get_user_model()
    users_with_email = User.objects.exclude(email="").count()
    verified_email_count = EmailAddress.objects.filter(verified=True).count()
    mfa_user_count = Authenticator.objects.values("user_id").distinct().count()
    context = {
        **admin.site.each_context(request),
        "title": "Güvenlik ve Sosyal Giriş Ayarları",
        "provider_rows": provider_rows(),
        "email_verification": getattr(settings, "ACCOUNT_EMAIL_VERIFICATION", ""),
        "social_email_verification": getattr(settings, "SOCIALACCOUNT_EMAIL_VERIFICATION", ""),
        "mfa_supported_types": ", ".join(getattr(settings, "MFA_SUPPORTED_TYPES", [])),
        "users_with_email": users_with_email,
        "verified_email_count": verified_email_count,
        "mfa_user_count": mfa_user_count,
    }
    return TemplateResponse(request, "admin/auth_security.html", context)


class ProfessionalAdminMixin:
    actions = (export_selected_as_csv,)
    list_per_page = 50
    save_on_top = True

    def get_list_select_related(self, request):
        related_fields = [
            field.name
            for field in self.model._meta.fields
            if field.many_to_one and not field.remote_field.model._meta.proxy
        ]
        return tuple(related_fields[:5])

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        for name in ("created_at", "updated_at", "last_synced_at", "last_sync_at", "fetched_at"):
            if _has_field(self.model, name) and name not in fields:
                fields.append(name)
        return tuple(fields)

    @admin.display(description="Durum")
    def status_badge(self, obj):
        value = getattr(obj, "status", None)
        if not value:
            value = "active" if getattr(obj, "is_active", False) else "passive"
        palette = {
            "completed": ("#166534", "#dcfce7"),
            "success": ("#166534", "#dcfce7"),
            "active": ("#166534", "#dcfce7"),
            "connected": ("#166534", "#dcfce7"),
            "excellent": ("#166534", "#dcfce7"),
            "good": ("#0f766e", "#ccfbf1"),
            "running": ("#1d4ed8", "#dbeafe"),
            "pending": ("#92400e", "#fef3c7"),
            "watch": ("#92400e", "#fef3c7"),
            "warning": ("#92400e", "#fef3c7"),
            "failed": ("#991b1b", "#fee2e2"),
            "error": ("#991b1b", "#fee2e2"),
            "expired": ("#991b1b", "#fee2e2"),
            "disconnected": ("#991b1b", "#fee2e2"),
            "critical": ("#991b1b", "#fee2e2"),
            "risky": ("#991b1b", "#fee2e2"),
            "passive": ("#475569", "#e2e8f0"),
        }
        color, bg = palette.get(str(value).lower(), ("#334155", "#e2e8f0"))
        label = _status_label_tr(obj, value)
        return format_html(
            '<span style="display:inline-block;padding:3px 9px;border-radius:999px;'
            'font-weight:600;color:{};background:{};">{}</span>',
            color,
            bg,
            label,
        )


class EnhancedAutoAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_per_page = 50
    search_fields = ("id",)

    def get_list_display(self, request):
        fields = [field.name for field in self.model._meta.fields]
        preferred = [
            "id", "name", "title", "display_name", "user", "organization", "platform",
            "platform_account", "status", "status_badge", "is_active", "created_at", "updated_at",
        ]
        display = []
        for name in preferred:
            if name == "status_badge" and ("status" in fields or "is_active" in fields):
                display.append(name)
            elif name in fields:
                display.append(name)
        if not display:
            display = fields[:6]
        return tuple(dict.fromkeys(display[:8]))

    def get_search_fields(self, request):
        candidates = [
            field.name
            for field in self.model._meta.fields
            if field.get_internal_type() in {"CharField", "TextField", "EmailField", "SlugField"}
        ]
        return tuple(candidates[:8])

    def get_list_filter(self, request):
        candidates = []
        for name in ("status", "is_active", "platform", "marketplace", "created_at", "updated_at"):
            if _has_field(self.model, name):
                candidates.append(name)
        return tuple(candidates[:6])


class PaymentTotalsAdminMixin:
    change_list_template = "admin/payment_totals_change_list.html"
    payment_total_fields = ()

    def _payment_total_rows(self, queryset):
        totals = []
        for key, label, fields in self.payment_total_fields:
            value = Decimal("0")
            for field_name in fields:
                value += queryset.aggregate(total=Sum(field_name)).get("total") or Decimal("0")
            totals.append({
                "key": key,
                "label": label,
                "value": f"{_tr_decimal(value)} TL",
            })
        return totals

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        if hasattr(response, "context_data") and "cl" in response.context_data:
            queryset = response.context_data["cl"].queryset
            response.context_data["payment_total_rows"] = self._payment_total_rows(queryset)
            response.context_data["payment_total_count"] = queryset.count()
        return response


CUSTOM_ADMIN_MODELS = set()


def safe_register(model, admin_class=None):
    if model in CUSTOM_ADMIN_MODELS:
        return
    try:
        admin.site.register(model, admin_class)
    except admin.sites.AlreadyRegistered:
        pass


CUSTOM_ADMIN_MODELS.update({
    Campaign, AdGroup, Creative, Ad, AdMetricHistory,
    SocialPost, SocialPostMetricHistory, Influencer, InfluencerMetricHistory,
    MembershipPlan, UserSubscription, ReferralCode, ReferralProgramSetting, ReferralProgramRule, ReferralReward, Organization, OrganizationMember, AgencyClient,
    PaymentMethod, AICreditPackage, AICreditLedger, UserAICreditBalance, FeatureUsageLedger,
    ProductResearchPackage, ProductResearchLedger, UserProductResearchBalance,
    Marketplace, MarketplaceAccount, MarketplaceSyncRun, Product, ProductVariant,
    MarketplaceListing, MarketplaceListingMetricHistory, MarketplaceProductChangeHistory,
    MarketplaceProductResearch, MarketplaceProductResearchMetricHistory,
    RawDataSnapshot, PlatformAccount, PlatformSyncJob, SystemErrorLog, Notification,
    CampaignOctoAnalysis, CampaignOctoRecommendation,
    Invoice, Payment, PaymentTransaction, BillingInfo,
    OctoTaskRule, OctoTaskInstance, OctoTaskActionLog,
    PlatformConnection,
    SaaSAICreditPool,
    AdminManagedCelerySchedule,
})


@admin.register(Campaign)
class CampaignAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("name", "user", "platform_account", "status_badge", "is_active", "last_synced_at")
    search_fields = ("name", "platform_campaign_id")
    list_filter = ("status", "is_active")
    date_hierarchy = "last_synced_at"


@admin.register(AdGroup)
class AdGroupAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("name", "user", "campaign", "status_badge", "is_active", "last_synced_at")
    search_fields = ("name", "platform_adgroup_id")
    list_filter = ("status", "is_active")
    autocomplete_fields = ("campaign",)
    date_hierarchy = "last_synced_at"


@admin.register(Creative)
class CreativeAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("name", "user", "platform_account", "creative_type", "updated_at")
    search_fields = ("name", "title", "platform_creative_id")
    list_filter = ("creative_type",)
    date_hierarchy = "updated_at"


@admin.register(Ad)
class AdAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("name", "user", "source_type", "platform_account", "campaign", "landing_page", "status_badge", "is_active", "last_synced_at")
    search_fields = ("name", "headline", "platform_ad_id", "ad_library_id", "landing_url")
    list_filter = ("source_type", "status", "is_active")
    autocomplete_fields = ("platform_account", "campaign", "ad_group", "creative")
    date_hierarchy = "last_synced_at"

    @admin.display(description="Landing", ordering="landing_url")
    def landing_page(self, obj):
        if not obj.landing_url:
            return "-"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">Hedef sayfayı aç</a>',
            obj.landing_url,
        )


@admin.register(AdMetricHistory)
class AdMetricHistoryAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("ad", "date", "impressions", "clicks", "spend", "ctr", "conversions", "conversion_value")
    list_filter = ("date", "is_competitor_snapshot")
    search_fields = ("ad__name", "ad__platform_ad_id")
    autocomplete_fields = ("ad",)
    date_hierarchy = "date"


@admin.register(SocialPost)
class SocialPostAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("caption", "user", "platform_connection", "post_type", "posted_at", "last_synced_at", "is_active")
    list_filter = ("post_type", "is_active", "posted_at")
    search_fields = ("caption", "platform_post_id", "permalink")


@admin.register(SocialPostMetricHistory)
class SocialPostMetricHistoryAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("social_post", "date", "impressions", "reach", "engagement", "engagement_rate")
    list_filter = ("date",)
    search_fields = ("social_post__caption", "social_post__platform_post_id")


@admin.register(Influencer)
class InfluencerAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("display_name", "platform", "handle", "category", "follower_count", "engagement_rate", "source", "is_active")
    list_filter = ("platform", "category", "source", "is_verified", "is_active")
    search_fields = ("display_name", "handle", "normalized_handle", "country", "city")


@admin.register(InfluencerMetricHistory)
class InfluencerMetricHistoryAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("influencer", "date", "follower_count", "avg_likes", "avg_comments", "avg_views", "engagement_rate")
    list_filter = ("date",)
    search_fields = ("influencer__display_name", "influencer__handle")


@admin.register(UserProfile)
class UserProfileAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = (
        "user",
        "allow_concurrent_sessions",
        "active_session_last_seen",
        "pending_deletion",
        "updated_at",
    )
    list_filter = ("allow_concurrent_sessions", "pending_deletion")
    search_fields = ("user__username", "user__email", "user__first_name", "user__last_name")
    readonly_fields = ("active_session_key", "active_session_last_seen", "created_at", "updated_at")


for model in [
    Platform,
    CampaignMetricHistory, AdGroupMetricHistory, CreativeMetricHistory,
    CreativeTemplate, CreativeProject, GeneratedContent,
    BudgetOptimizationRule, BudgetOptimizationLog,
    AnomalyAlert, OpportunityWindow, NotificationPreference, ActivityLog,
    RawPlatformData, OctoScoreHistory, AIRecommendationHistory,
]:
    safe_register(model, EnhancedAutoAdmin)


@admin.register(MembershipPlan)
class MembershipPlanAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = (
        "display_name",
        "name",
        "plan_type",
        "price",
        "ai_analysis_per_week",
        "ai_analysis_per_month",
        "ai_credits_per_month",
        "marketplace_product_research_per_month",
        "marketplace_price_check_per_month",
        "is_active",
        "order",
    )
    list_filter = ("plan_type", "is_active", "is_most_popular", "has_team_members")
    search_fields = ("name", "display_name")
    ordering = ("plan_type", "order", "price")
    fieldsets = (
        ("Plan bilgisi", {
            "fields": ("name", "display_name", "plan_type", "features", "order", "is_active")
        }),
        ("Fiyat ve vitrin", {
            "fields": ("price", "price_with_kdv", "badge", "badge_color", "is_most_popular")
        }),
        ("AI limitleri", {
            "fields": (
                "ai_analysis_per_week",
                "ai_analysis_per_month",
                "ai_recommendation_per_week",
                "ai_recommendation_per_month",
                "ai_credits_per_month",
                "allow_ai_credit_topup",
                "ai_content_generation",
                "has_ai_content_generation",
                "marketplace_product_research_per_month",
                "marketplace_price_check_per_month",
            ),
            "description": "0 limit yok anlamına gelir. 9999 ve üzeri sınırsız kabul edilir.",
        }),
        ("Hesap ve takip limitleri", {
            "fields": (
                "max_instagram_accounts",
                "max_content_fetch_count",
                "content_fetch_period_days",
                "auto_fetch_enabled",
                "auto_fetch_frequency",
                "max_competitors",
                "competitor_fetch_enabled",
                "competitor_fetch_frequency",
                "competitor_auto_discovery",
            )
        }),
        ("Ajans ve ekip limitleri", {
            "fields": ("has_team_members", "included_seats", "max_team_members", "max_client_accounts")
        }),
        ("Özellik izinleri", {
            "fields": (
                "max_campaign_templates",
                "has_campaign_calendar",
                "has_ab_test_campaigns",
                "has_content_calendar",
                "content_calendar_days",
                "has_analytics",
                "has_advanced_reporting",
                "has_opportunity_finder",
                "has_api_access",
                "has_white_label",
                "has_crisis_alert",
                "has_strategy_webinar",
                "priority_support",
                "has_dedicated_manager",
                "max_products",
                "max_campaigns",
            )
        }),
    )


@admin.register(PlanAuthorizationPolicy)
class PlanAuthorizationPolicyAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    """Single admin surface for every runtime entitlement and sync limit."""

    list_display = (
        "display_name", "plan_type_badge", "is_active", "included_seats", "max_client_accounts", "max_instagram_accounts", "max_competitors",
        "ai_credits_per_month", "ai_analysis_per_month", "ai_recommendation_per_month",
        "marketplace_product_research_per_month", "marketplace_price_check_per_month",
        "ad_sync_interval_minutes", "competitor_sync_interval_minutes",
        "organic_sync_interval_minutes", "marketplace_sync_interval_minutes",
    )
    list_editable = (
        "is_active", "included_seats", "max_client_accounts", "max_instagram_accounts", "max_competitors", "ai_credits_per_month",
        "ai_analysis_per_month", "ai_recommendation_per_month",
        "marketplace_product_research_per_month", "marketplace_price_check_per_month",
        "ad_sync_interval_minutes", "competitor_sync_interval_minutes",
        "organic_sync_interval_minutes", "marketplace_sync_interval_minutes",
    )
    ordering = ("order", "price")
    list_filter = ("plan_type", "is_active")
    search_fields = ("name", "display_name")
    save_on_top = True
    fieldsets = (
        ("Plan", {"fields": ("display_name", "name", "plan_type", "is_active", "features")}),
        ("Hesap, veri ve rakip limitleri", {"fields": (
            "max_instagram_accounts", "max_content_fetch_count", "content_fetch_period_days",
            "max_competitors", "competitor_fetch_enabled", "competitor_auto_discovery",
            "max_products", "max_campaigns",
        )}),
        ("AI kredi ve işlem limitleri", {"fields": (
            "ai_credits_per_month", "allow_ai_credit_topup", "ai_analysis_per_month",
            "ai_recommendation_per_month", "ai_analysis_per_week", "ai_recommendation_per_week",
            "ai_content_generation", "has_ai_content_generation",
        )}),
        ("Pazaryeri limitleri", {"fields": (
            "marketplace_product_research_per_month", "marketplace_price_check_per_month",
        )}),
        ("Senkronizasyon tarifesi", {"fields": (
            "auto_fetch_enabled", "auto_fetch_frequency", "ad_sync_interval_minutes",
            "competitor_sync_interval_minutes", "organic_sync_interval_minutes",
            "marketplace_sync_interval_minutes", "max_sync_records",
            "allow_manual_ad_sync", "allow_manual_competitor_sync",
            "allow_manual_organic_sync", "allow_manual_marketplace_sync",
        ), "description": "Dakika değerleri görev dispatcher'ları tarafından doğrudan kullanılır."}),
        ("Kampanya ve içerik", {"fields": (
            "max_campaign_templates", "has_campaign_calendar", "has_ab_test_campaigns",
            "has_content_calendar", "content_calendar_days",
        )}),
        ("Modül izinleri", {"fields": (
            "has_analytics", "has_advanced_reporting", "has_opportunity_finder", "has_api_access",
            "has_white_label", "has_team_members", "has_crisis_alert", "has_strategy_webinar",
        )}),
        ("Ajans, ekip ve destek", {"fields": (
            "included_seats", "max_team_members", "max_client_accounts", "priority_support",
            "has_dedicated_manager",
        )}),
    )

    @admin.display(description="Plan türü", ordering="plan_type")
    def plan_type_badge(self, obj):
        labels = {
            MembershipPlan.PLAN_TYPE_AGENCY: ("AJANS", "#0891b2"),
            MembershipPlan.PLAN_TYPE_BUSINESS: ("İŞLETME", "#4f46e5"),
            MembershipPlan.PLAN_TYPE_LEGACY: ("ESKİ PLAN", "#64748b"),
        }
        label, color = labels.get(obj.plan_type, ("ESKİ PLAN", "#64748b"))
        return format_html(
            '<span style="display:inline-block;padding:3px 8px;border-radius:999px;'
            'background:{};color:#fff;font-weight:700;font-size:11px;">{}</span>',
            color,
            label,
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserSubscription)
class UserSubscriptionAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("user", "plan", "organization", "billing_period", "start_date", "end_date", "next_renewal_date", "is_active", "auto_renew", "payment_method_display")
    list_filter = ("is_active", "auto_renew", "billing_period", "plan__plan_type", "next_renewal_date")
    search_fields = ("user__email", "user__username", "plan__display_name", "organization__name")
    autocomplete_fields = ("user", "plan", "organization", "default_payment_method")
    readonly_fields = ("created_at", "updated_at", "last_renewed_at")

    @admin.display(description="Kart")
    def payment_method_display(self, obj):
        method = obj.default_payment_method
        if not method:
            return "-"
        return f"{method.card_brand} **** {method.last4}"


@admin.register(ReferralCode)
class ReferralCodeAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("code", "owner", "reward_type", "reward_amount", "awarded_count_display", "max_uses", "valid_until", "is_active", "created_at")
    list_filter = ("is_active", "reward_type", "valid_until", "created_at")
    search_fields = ("code", "owner__email", "owner__username", "description")
    autocomplete_fields = ("owner",)
    readonly_fields = ("created_at", "updated_at", "awarded_count_display")
    date_hierarchy = "created_at"

    @admin.display(description="Verilen hak")
    def awarded_count_display(self, obj):
        return obj.awarded_count


@admin.register(ReferralProgramSetting)
class ReferralProgramSettingAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("is_enabled", "default_reward_type", "default_reward_amount", "updated_at")
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not ReferralProgramSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReferralProgramRule)
class ReferralProgramRuleAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("name", "plan_type", "billing_period", "new_customer_discount_percent", "reward_type", "reward_amount", "priority", "is_active", "updated_at")
    list_filter = ("is_active", "plan_type", "billing_period", "reward_type")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("priority", "plan_type", "billing_period", "name")


@admin.register(ReferralReward)
class ReferralRewardAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("referral_code", "referrer", "referred_user", "reward_type", "reward_amount", "status", "awarded_at", "created_at")
    list_filter = ("status", "reward_type", "created_at", "awarded_at")
    search_fields = ("referral_code__code", "referrer__email", "referrer__username", "referred_user__email", "referred_user__username", "note")
    autocomplete_fields = ("referral_code", "referrer", "referred_user", "subscription", "payment")
    readonly_fields = ("created_at", "updated_at", "awarded_at")
    date_hierarchy = "created_at"
    actions = ("grant_selected_referral_rewards", export_selected_as_csv)

    @admin.action(description="Seçili bekleyen referans haklarını tanımla")
    def grant_selected_referral_rewards(self, request, queryset):
        from core.services.referrals import grant_referral_reward

        granted = 0
        for reward in queryset.filter(status=ReferralReward.STATUS_PENDING):
            grant_referral_reward(reward)
            granted += 1
        self.message_user(request, f"{granted} referans hakkı tanımlandı.", messages.SUCCESS)


def run_account_deletion_lifecycle(modeladmin, request, queryset):
    from core.tasks.maintenance_tasks import sync_account_deletion_lifecycle

    async_result = sync_account_deletion_lifecycle.delay()
    modeladmin.message_user(
        request,
        f"Hesap silme/aski lifecycle gorevi kuyruga alindi. Task id: {async_result.id}",
        messages.SUCCESS,
    )


run_account_deletion_lifecycle.short_description = "Hesap silme/aski lifecycle gorevini calistir"


@admin.register(AccountDeletionRecord)
class AccountDeletionRecordAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = (
        "account_display",
        "email",
        "status_badge",
        "requested_at",
        "suspends_at",
        "scheduled_deletion_at",
        "cancelled_at",
        "deleted_at",
    )
    list_filter = ("status", "requested_at", "suspends_at", "scheduled_deletion_at", "deleted_at")
    search_fields = ("username", "email", "full_name", "note", "user__username", "user__email")
    readonly_fields = (
        "user",
        "username",
        "email",
        "full_name",
        "status",
        "requested_at",
        "suspends_at",
        "scheduled_deletion_at",
        "cancelled_at",
        "deleted_at",
        "note",
        "created_at",
        "updated_at",
    )
    actions = (export_selected_as_csv, run_account_deletion_lifecycle)
    date_hierarchy = "requested_at"

    fieldsets = (
        ("Uye ozeti", {"fields": ("user", "username", "email", "full_name")}),
        ("Silme / aski sureci", {
            "fields": (
                "status",
                "requested_at",
                "suspends_at",
                "scheduled_deletion_at",
                "cancelled_at",
                "deleted_at",
                "note",
            )
        }),
        ("Kayit", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def account_display(self, obj):
        label = obj.full_name or obj.username or obj.email or "-"
        if obj.user_id:
            return format_html("<strong>{}</strong><br><small>user_id={}</small>", label, obj.user_id)
        return format_html("<strong>{}</strong><br><small>kalici silinmis kullanici</small>", label)

    account_display.short_description = "Uye"

    def status_badge(self, obj):
        colors = {
            AccountDeletionRecord.STATUS_REQUESTED: ("#eef2ff", "#3730a3"),
            AccountDeletionRecord.STATUS_SCHEDULED: ("#fff7ed", "#c2410c"),
            AccountDeletionRecord.STATUS_SUSPENDED: ("#fef2f2", "#b42318"),
            AccountDeletionRecord.STATUS_CANCELLED: ("#ecfdf3", "#067647"),
            AccountDeletionRecord.STATUS_DELETED: ("#111827", "#ffffff"),
        }
        bg, fg = colors.get(obj.status, ("#f2f4f7", "#344054"))
        return format_html(
            '<span style="display:inline-flex;align-items:center;border-radius:999px;padding:6px 10px;font-weight:800;background:{};color:{};">{}</span>',
            bg,
            fg,
            obj.get_status_display(),
        )

    status_badge.short_description = "Durum"


@admin.register(SuspendedAccountDeletionRecord)
class SuspendedAccountDeletionRecordAdmin(AccountDeletionRecordAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).filter(status=AccountDeletionRecord.STATUS_SUSPENDED)


@admin.register(DeletedAccountDeletionRecord)
class DeletedAccountDeletionRecordAdmin(AccountDeletionRecordAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).filter(status=AccountDeletionRecord.STATUS_DELETED)


@admin.register(Organization)
class OrganizationAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("name", "owner", "active_plan", "additional_seats", "seat_usage", "active_client_count", "is_active", "created_at")
    list_filter = ("is_active", "active_plan__plan_type")
    search_fields = ("name", "owner__email", "owner__username")
    autocomplete_fields = ("owner", "active_plan")

    @admin.display(description="Koltuk kullanımı")
    def seat_usage(self, obj):
        return f"{obj.active_member_count()} / {obj.seat_limit}"


@admin.register(OrganizationMember)
class OrganizationMemberAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("organization", "user", "role_group", "is_active", "joined_at")
    list_filter = ("role", "is_active")
    search_fields = ("organization__name", "user__email", "user__username", "invited_email")
    autocomplete_fields = ("organization", "user")


@admin.register(AgencyRoleGroup)
class AgencyRoleGroupAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("organization", "name", "is_active", "updated_at")
    list_filter = ("is_active", "can_manage_members", "can_manage_billing")
    search_fields = ("organization__name", "name", "description")
    autocomplete_fields = ("organization",)


@admin.register(AgencyClient)
class AgencyClientAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("name", "organization", "website", "contact_email", "is_active", "created_at")
    list_filter = ("is_active", "organization")
    search_fields = ("name", "legal_name", "organization__name", "contact_email")
    autocomplete_fields = ("organization",)


@admin.register(AICreditPackage)
class AICreditPackageAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("display_name", "name", "credits", "price", "price_with_kdv", "is_active", "order")
    list_filter = ("is_active",)
    search_fields = ("name", "display_name")
    ordering = ("order", "price")


@admin.register(AIOperationTariff)
class AIOperationTariffAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    change_list_template = "admin/ai_operation_tariff_change_list.html"
    list_display = (
        "display_name", "creative_studio_stage", "key", "category", "credit_cost", "model_name",
        "max_input_tokens", "max_output_tokens", "max_calls", "cache_timeout_seconds", "max_cost_usd",
        "safety_margin_percent", "uses_openai", "is_active", "updated_at",
    )
    list_editable = (
        "credit_cost", "model_name", "max_input_tokens", "max_output_tokens", "max_calls", "cache_timeout_seconds", "max_cost_usd",
        "safety_margin_percent", "is_active",
    )
    list_filter = ("category", "uses_openai", "is_active", "model_name")
    search_fields = ("display_name", "key", "category", "note")
    ordering = ("category", "display_name")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Creative Studio aşaması")
    def creative_studio_stage(self, obj):
        stages = {
            "creative-studio-prompt": ("1", "Ürün analizi", "#2563eb"),
            "creative-studio-content": ("2", "Ara öneri / metin", "#7c3aed"),
            "creative-studio-final-review": ("3", "Final kalite kontrolü", "#059669"),
            "creative-studio-image": ("4", "Görsel üretimi", "#ea580c"),
        }
        stage = stages.get(obj.key)
        if not stage:
            return "—"
        number, label, color = stage
        return format_html(
            '<span style="display:inline-flex;align-items:center;gap:5px;padding:4px 7px;'
            'border-radius:999px;background:{}18;color:{};font-weight:800;white-space:nowrap;">'
            '{} · {}</span>',
            color, color, number, label,
        )


@admin.register(ProductResearchPackage)
class ProductResearchPackageAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("display_name", "name", "units", "price", "price_with_kdv", "is_active", "order")
    list_filter = ("is_active",)
    search_fields = ("name", "display_name")
    ordering = ("order", "price")


@admin.register(PaymentMethod)
class PaymentMethodAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("user", "provider", "card_brand", "last4", "expiry_month", "expiry_year", "is_default", "is_active", "updated_at")
    list_filter = ("provider", "card_brand", "is_default", "is_active", "expiry_year")
    search_fields = ("user__email", "user__username", "last4", "card_holder")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
    exclude = ("token_encrypted",)
    date_hierarchy = "created_at"


@admin.register(AICreditLedger)
class AICreditLedgerAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = (
        "created_at",
        "user",
        "organization",
        "islem_turu",
        "kontor_hareketi",
        "kalan_kontor",
        "reference",
        "note",
    )
    list_filter = ("action", "organization", "created_at")
    search_fields = ("user__email", "user__username", "organization__name", "reference", "note")
    autocomplete_fields = ("user", "organization", "subscription", "package")
    readonly_fields = ("created_at", "islem_turu", "kontor_hareketi", "kalan_kontor")
    date_hierarchy = "created_at"

    fieldsets = (
        ("Kontor hareketi", {
            "fields": (
                "user",
                "organization",
                "subscription",
                "package",
                "action",
                "amount",
                "balance_after",
                "reference",
                "note",
                "created_at",
            )
        }),
        ("Okunabilir ozet", {
            "fields": ("islem_turu", "kontor_hareketi", "kalan_kontor")
        }),
    )

    @admin.display(description="Islem turu", ordering="action")
    def islem_turu(self, obj):
        return obj.get_action_display()

    @admin.display(description="Kontor hareketi", ordering="amount")
    def kontor_hareketi(self, obj):
        amount = obj.amount or 0
        if amount < 0:
            return format_html('<strong style="color:#b91c1c;">-{} kullanıldı</strong>', _tr_int(abs(amount)))
        return format_html('<strong style="color:#15803d;">+{} yüklendi</strong>', _tr_int(amount))

    @admin.display(description="Kalan kontor", ordering="balance_after")
    def kalan_kontor(self, obj):
        return _tr_int(obj.balance_after)


@admin.register(UserAICreditBalance)
class UserAICreditBalanceAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = (
        "user",
        "organization",
        "cycle_start",
        "cycle_end",
        "plan_display",
        "purchased_display",
        "used_display",
        "balance_display",
        "updated_at",
    )
    list_filter = ("cycle_start", "cycle_end", "organization")
    search_fields = ("user__email", "user__username", "organization__name")
    autocomplete_fields = ("user", "organization", "subscription")
    readonly_fields = ("updated_at",)
    ordering = ("-updated_at",)

    @admin.display(description="Plan kredisi", ordering="plan_credits")
    def plan_display(self, obj):
        return _tr_int(obj.plan_credits)

    @admin.display(description="Satın alınan", ordering="purchased_credits")
    def purchased_display(self, obj):
        return _tr_int(obj.purchased_credits)

    @admin.display(description="Kullanılan", ordering="used_credits")
    def used_display(self, obj):
        return _tr_int(obj.used_credits)

    @admin.display(description="Kalan", ordering="current_balance")
    def balance_display(self, obj):
        return _tr_int(obj.current_balance)


@admin.register(ProductResearchLedger)
class ProductResearchLedgerAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "user", "organization", "action", "amount", "balance_after", "cycle_start", "cycle_end", "package", "reference")
    list_filter = ("action", "organization", "cycle_start", "created_at")
    search_fields = ("user__email", "user__username", "organization__name", "reference", "note")
    autocomplete_fields = ("user", "organization", "package")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    actions = (export_selected_as_csv,)


@admin.register(UserProductResearchBalance)
class UserProductResearchBalanceAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("user", "organization", "cycle_start", "cycle_end", "purchased_units", "used_units", "current_balance", "updated_at")
    list_filter = ("cycle_start", "cycle_end", "organization")
    search_fields = ("user__email", "user__username", "organization__name")
    autocomplete_fields = ("user", "organization")
    readonly_fields = ("updated_at",)
    ordering = ("-cycle_start", "-updated_at")


@admin.register(FeatureUsageLedger)
class FeatureUsageLedgerAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = (
        "created_at",
        "user",
        "organization",
        "operation_display",
        "status_display",
        "tariff_display",
        "credit_detail_display",
        "credit_state_display",
        "token_total_display",
        "units",
        "provider_units",
        "estimated_cost",
        "reference",
    )
    list_filter = ("operation", "status", "organization", "created_at")
    search_fields = ("user__email", "user__username", "organization__name", "reference", "note", "metadata")
    autocomplete_fields = ("user", "organization", "subscription")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    actions = (export_selected_as_csv,)

    @admin.display(description="Kullanim turu", ordering="operation")
    def operation_display(self, obj):
        return obj.get_operation_display()

    @admin.display(description="Durum", ordering="status")
    def status_display(self, obj):
        colors = {
            FeatureUsageLedger.STATUS_ALLOWED: "#15803d",
            FeatureUsageLedger.STATUS_BLOCKED: "#b45309",
            FeatureUsageLedger.STATUS_FAILED: "#b91c1c",
        }
        return format_html(
            '<strong style="color:{};">{}</strong>',
            colors.get(obj.status, "#334155"),
            obj.get_status_display(),
        )

    @admin.display(description="Tarife")
    def tariff_display(self, obj):
        return (obj.metadata or {}).get("tariff_key") or "-"

    @admin.display(description="Kredi: gerekli / mevcut")
    def credit_detail_display(self, obj):
        metadata = obj.metadata or {}
        required = metadata.get("required_credits", metadata.get("tariff_credits"))
        available = metadata.get("available_credits")
        if required is None:
            return "-"
        if available is None:
            return f"{_tr_int(required)} kredi"
        color = "#b91c1c" if obj.status == FeatureUsageLedger.STATUS_BLOCKED else "#334155"
        return format_html(
            '<strong style="color:{};">{} / {}</strong>',
            color, _tr_int(required), _tr_int(available),
        )

    @admin.display(description="Kredi durumu")
    def credit_state_display(self, obj):
        state = (obj.metadata or {}).get("credit_state") or "-"
        labels = {
            "consumed": "Kullanıldı",
            "blocked": "Yetersiz bakiye",
            "refunded": "İade edildi",
        }
        return labels.get(state, state)

    @admin.display(description="Gerçek token")
    def token_total_display(self, obj):
        tariff_key = (obj.metadata or {}).get("tariff_key") or ""
        queryset = OpenAITokenUsageLedger.objects.filter(
            user=obj.user,
            organization=obj.organization,
            operation_key=tariff_key,
            used_at__gte=obj.created_at,
            used_at__lte=obj.created_at + timedelta(minutes=10),
        )
        total = queryset.aggregate(value=Sum("total_tokens"))["value"] or 0
        return _tr_int(total) if total else "-"


@admin.register(SaaSAICreditPool)
class SaaSAICreditPoolAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("month", "provider_name", "purchased_display", "used_display", "remaining_display", "usage_percent_display", "updated_at")
    list_filter = ("month", "provider_name")
    search_fields = ("provider_name", "note")
    readonly_fields = ("remaining_display", "usage_percent_display", "created_at", "updated_at")
    date_hierarchy = "month"
    ordering = ("-month",)

    @admin.display(description="Aylık alınan kontör", ordering="purchased_credits")
    def purchased_display(self, obj):
        return _tr_int(obj.purchased_credits)

    @admin.display(description="Kullanılan kontör", ordering="used_credits")
    def used_display(self, obj):
        return _tr_int(obj.used_credits)

    @admin.display(description="Kalan kontör")
    def remaining_display(self, obj):
        return _tr_int(obj.remaining_credits)

    @admin.display(description="Kullanım yüzdesi")
    def usage_percent_display(self, obj):
        return f"%{_tr_decimal(obj.usage_percent)}"


@admin.register(OpenAITokenUsageLedger)
class OpenAITokenUsageLedgerAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    change_list_template = "admin/openai_token_usage_change_list.html"
    list_display = (
        "used_at", "user", "organization", "model_name", "input_display",
        "output_display", "total_display", "usage_kind", "operation_key", "reference",
    )
    list_filter = ("usage_kind", "operation_key", "model_name", "organization", "used_at")
    search_fields = ("user__email", "user__username", "organization__name", "operation_key", "request_id", "reference", "note")
    autocomplete_fields = ("user", "organization")
    readonly_fields = ("created_at",)
    date_hierarchy = "used_at"
    ordering = ("-used_at", "-id")

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        try:
            queryset = response.context_data["cl"].queryset
            totals = queryset.aggregate(
                input_sum=Sum("input_tokens", filter=~Q(model_name="provider-unattributed")),
                output_sum=Sum("output_tokens", filter=~Q(model_name="provider-unattributed")),
                token_sum=Sum("total_tokens"),
                attributed_sum=Sum("total_tokens", filter=Q(user__isnull=False)),
                unassigned_sum=Sum("total_tokens", filter=Q(user__isnull=True)),
            )
            response.context_data["token_totals"] = {
                key: int(value or 0) for key, value in totals.items()
            }
            response.context_data["token_record_count"] = queryset.count()
            response.context_data["token_user_totals"] = list(
                queryset.filter(user__isnull=False)
                .values("user_id", "user__email", "user__username")
                .annotate(
                    input_sum=Sum("input_tokens"),
                    output_sum=Sum("output_tokens"),
                    token_sum=Sum("total_tokens"),
                )
                .order_by("-token_sum", "user__email")[:100]
            )
        except (AttributeError, KeyError):
            pass
        return response

    @admin.display(description="Giris token", ordering="input_tokens")
    def input_display(self, obj):
        return _tr_int(obj.input_tokens)

    @admin.display(description="Cikis token", ordering="output_tokens")
    def output_display(self, obj):
        return _tr_int(obj.output_tokens)

    @admin.display(description="Toplam token", ordering="total_tokens")
    def total_display(self, obj):
        return _tr_int(obj.total_tokens)


@admin.register(TavilyAPIPool)
class TavilyAPIPoolAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("month", "provider_name", "monthly_limit_display", "used_display", "remaining_display", "usage_percent_display", "rate_limit", "updated_at")
    list_filter = ("month", "provider_name", "rate_limit")
    search_fields = ("provider_name", "note")
    readonly_fields = ("remaining_display", "usage_percent_display", "created_at", "updated_at")
    date_hierarchy = "month"
    ordering = ("-month",)

    def has_module_permission(self, request):
        try:
            return self.model._meta.db_table in connection.introspection.table_names()
        except Exception:
            return False

    def get_model_perms(self, request):
        if not self.has_module_permission(request):
            return {}
        return super().get_model_perms(request)

    @admin.display(description="Aylik hak", ordering="monthly_limit")
    def monthly_limit_display(self, obj):
        return _tr_int(obj.monthly_limit)

    @admin.display(description="Kullanilan", ordering="used_requests")
    def used_display(self, obj):
        return _tr_int(obj.used_requests)

    @admin.display(description="Kalan")
    def remaining_display(self, obj):
        return _tr_int(obj.remaining_requests)

    @admin.display(description="Kullanim yuzdesi")
    def usage_percent_display(self, obj):
        return f"%{_tr_decimal(obj.usage_percent)}"


@admin.register(TavilyAPIUsageLedger)
class TavilyAPIUsageLedgerAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "pool", "status_display", "amount", "balance_after", "response_status", "reference", "query_preview")
    list_filter = ("status", "pool__month", "response_status", "created_at")
    search_fields = ("query", "reference", "error_message")
    autocomplete_fields = ("pool",)
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    actions = (export_selected_as_csv,)

    def has_module_permission(self, request):
        try:
            return self.model._meta.db_table in connection.introspection.table_names()
        except Exception:
            return False

    def get_model_perms(self, request):
        if not self.has_module_permission(request):
            return {}
        return super().get_model_perms(request)

    @admin.display(description="Durum", ordering="status")
    def status_display(self, obj):
        colors = {
            TavilyAPIUsageLedger.STATUS_ALLOWED: "#15803d",
            TavilyAPIUsageLedger.STATUS_BLOCKED: "#b45309",
            TavilyAPIUsageLedger.STATUS_FAILED: "#b91c1c",
        }
        return format_html(
            '<strong style="color:{};">{}</strong>',
            colors.get(obj.status, "#334155"),
            obj.get_status_display(),
        )

    @admin.display(description="Sorgu")
    def query_preview(self, obj):
        value = (obj.query or "").strip()
        return value[:90] + ("..." if len(value) > 90 else "")


@admin.register(Marketplace)
class MarketplaceAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = (
        "name", "code", "research_enabled", "browser_verification_enabled",
        "search_priority", "max_results", "timeout_seconds", "credit_multiplier",
        "is_active", "order", "updated_at",
    )
    list_editable = (
        "research_enabled", "browser_verification_enabled", "search_priority",
        "max_results", "timeout_seconds", "credit_multiplier", "is_active", "order",
    )
    list_filter = ("is_active", "research_enabled", "browser_verification_enabled")
    search_fields = ("name", "code")
    ordering = ("search_priority", "order", "name")


@admin.register(MarketplaceAccount)
class MarketplaceAccountAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("store_name", "marketplace", "user", "organization", "sync_mode", "sync_product_limit", "is_active", "last_sync_at")
    list_filter = ("marketplace", "sync_mode", "is_active")
    search_fields = ("store_name", "seller_id", "user__email", "user__username", "organization__name")
    autocomplete_fields = ("marketplace", "user", "organization", "subscription", "agency_client")
    readonly_fields = ("created_at", "updated_at", "last_sync_at")


@admin.register(MarketplaceSyncRun)
class MarketplaceSyncRunAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("marketplace_account", "sync_type", "status", "product_limit", "fetched_count", "created_count", "updated_count", "created_at")
    list_filter = ("sync_type", "status", "marketplace_account__marketplace")
    search_fields = ("marketplace_account__store_name", "marketplace_account__seller_id", "error_message")
    autocomplete_fields = ("marketplace_account", "requested_by")
    readonly_fields = ("created_at", "started_at", "finished_at")


@admin.register(Product)
class ProductAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("name", "sku", "barcode", "brand", "category_name", "purchase_price", "default_sale_price", "image_url", "user", "is_active")
    list_filter = ("is_active", "brand")
    search_fields = ("name", "sku", "barcode", "brand", "category_name", "user__email", "user__username")
    autocomplete_fields = ("user", "organization", "subscription", "agency_client")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ProductVariant)
class ProductVariantAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("product", "sku", "barcode", "color", "size", "purchase_price", "image_url", "is_active")
    list_filter = ("is_active", "color", "size")
    search_fields = ("product__name", "sku", "barcode", "color", "size")
    autocomplete_fields = ("product",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(MarketplaceListing)
class MarketplaceListingAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("product", "variant", "marketplace", "marketplace_account", "sale_price", "discounted_price", "stock", "rating_average", "review_count", "buybox_rank", "status", "last_synced_at")
    list_filter = ("marketplace", "status", "marketplace_account")
    search_fields = ("product__name", "platform_sku", "platform_barcode", "platform_product_id", "platform_category_name")
    autocomplete_fields = ("marketplace_account", "marketplace", "product", "variant")
    readonly_fields = ("created_at", "updated_at", "last_synced_at")


@admin.register(MarketplaceListingMetricHistory)
class MarketplaceListingMetricHistoryAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("listing", "date", "marketplace", "sale_price", "discounted_price", "stock", "status", "orders", "units_sold", "revenue", "view_count", "favorite_count", "return_count")
    list_filter = ("marketplace", "status", "date")
    search_fields = ("listing__product__name", "listing__platform_sku", "listing__platform_barcode", "product__sku")
    autocomplete_fields = ("listing", "marketplace_account", "marketplace", "product", "variant", "sync_run")
    readonly_fields = ("created_at",)
    date_hierarchy = "date"


@admin.register(MarketplaceProductChangeHistory)
class MarketplaceProductChangeHistoryAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("listing", "change_type", "field_name", "old_value", "new_value", "marketplace", "created_at")
    list_filter = ("change_type", "marketplace", "created_at")
    search_fields = ("listing__product__name", "product__sku", "field_name", "old_value", "new_value")
    autocomplete_fields = ("listing", "marketplace_account", "marketplace", "product", "variant", "sync_run")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"


@admin.register(MarketplaceProductResearch)
class MarketplaceProductResearchAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("title", "user", "search_mode", "progress_percent", "current_step", "min_price", "average_price", "track_price", "status", "created_at")
    list_filter = ("search_mode", "status", "source", "track_price", "created_at")
    search_fields = ("title", "prompt", "detected_product_name", "detected_category", "user__email", "user__username")
    autocomplete_fields = ("user", "organization", "subscription", "product", "selected_marketplaces")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"


@admin.register(MarketplaceProductResearchResult)
class MarketplaceProductResearchResultAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = (
        "title", "research", "marketplace", "seller_name", "total_price",
        "match_score", "authenticity_score", "verification_status", "is_eligible", "created_at",
    )
    list_filter = ("marketplace", "verification_status", "is_eligible", "created_at")
    search_fields = ("title", "seller_name", "product_url", "research__title")
    autocomplete_fields = ("research", "marketplace")
    readonly_fields = ("created_at", "verified_at")


@admin.register(MarketplaceProductResearchMetricHistory)
class MarketplaceProductResearchMetricHistoryAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("research", "user", "checked_at", "min_price", "max_price", "average_price", "recommended_price", "change_direction", "recommended_price_change", "result_count")
    list_filter = ("change_direction", "checked_at")
    search_fields = ("research__title", "research__detected_product_name", "user__email", "user__username")
    autocomplete_fields = ("research", "user", "organization", "subscription", "product")
    readonly_fields = ("created_at",)
    date_hierarchy = "checked_at"


@admin.register(RawDataSnapshot)
class RawDataSnapshotAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "platform",
        "platform_account",
        "source_type",
        "status",
        "external_id",
        "fetched_at",
        "created_at",
    )
    list_filter = ("platform", "source_type", "status", "fetched_at")
    search_fields = ("external_id", "external_parent_id", "error_message")
    readonly_fields = ("checksum", "created_at")
    date_hierarchy = "fetched_at"


@admin.register(PlatformAccount)
class PlatformAccountAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("platform", "account_name", "account_id", "user", "agency_client", "is_active", "last_sync", "updated_at")
    list_filter = ("platform", "is_active", "agency_client")
    search_fields = ("account_name", "account_id", "user__email", "user__username", "agency_client__name")
    autocomplete_fields = ("user", "platform", "connection", "agency_client")
    readonly_fields = ("created_at", "updated_at", "last_sync")
    date_hierarchy = "updated_at"
    actions = (export_selected_as_csv, queue_platform_account_sync, mark_selected_active, mark_selected_inactive)


class PlatformConnectionActiveFilter(admin.SimpleListFilter):
    title = "Aktiflik"
    parameter_name = "is_active"

    def lookups(self, request, model_admin):
        return (
            ("1", "Aktif"),
            ("0", "Pasif"),
        )

    def queryset(self, request, queryset):
        if self.value() == "1":
            return queryset.filter(is_active=True)
        if self.value() == "0":
            return queryset.filter(is_active=False)
        return queryset


@admin.register(PlatformConnection)
class PlatformConnectionAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("platform", "name", "user", "status_badge", "active_status_badge", "token_expiry", "last_sync", "updated_at")
    list_filter = ("platform", "status", PlatformConnectionActiveFilter, "token_expiry", "last_sync")
    search_fields = ("name", "user__email", "user__username", "platform__name", "platform__code")
    autocomplete_fields = ("user", "platform")
    readonly_fields = ("created_at", "updated_at", "last_sync")
    date_hierarchy = "updated_at"
    actions = (export_selected_as_csv, queue_token_refresh, mark_selected_active, mark_selected_inactive)

    @admin.display(description="Aktiflik", ordering="is_active")
    def active_status_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="display:inline-block;padding:3px 9px;border-radius:999px;'
                'font-weight:600;color:#166534;background:#dcfce7;">Aktif</span>'
            )
        return format_html(
            '<span style="display:inline-block;padding:3px 9px;border-radius:999px;'
            'font-weight:600;color:#475569;background:#e2e8f0;">Pasif</span>'
        )


@admin.register(PlatformSyncJob)
class PlatformSyncJobAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("platform_account", "user", "status_badge", "progress", "campaigns_count", "ads_count", "metrics_count", "started_at", "finished_at")
    list_filter = ("status", "platform_account__platform", "created_at")
    search_fields = ("platform_account__account_name", "platform_account__account_id", "user__email", "message", "error_message")
    autocomplete_fields = ("user", "platform_account")
    readonly_fields = ("created_at", "updated_at", "started_at", "finished_at", "result")
    date_hierarchy = "created_at"


@admin.register(AdminManagedCelerySchedule)
class AdminManagedCeleryScheduleAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("name", "task_name", "interval_display", "is_active", "last_run_at", "last_task_id", "last_error_short")
    list_filter = ("is_active", "interval_period", "created_at", "updated_at")
    search_fields = ("name", "task_name", "description", "last_task_id", "last_error")
    readonly_fields = ("last_run_at", "last_task_id", "last_error", "created_at", "updated_at")
    actions = (export_selected_as_csv, run_admin_managed_schedule_now, mark_selected_active, mark_selected_inactive)
    fieldsets = (
        ("Görev", {
            "fields": ("name", "task_name", "is_active", "description")
        }),
        ("Çalışma aralığı", {
            "fields": ("interval_every", "interval_period")
        }),
        ("Parametreler", {
            "description": "Args liste, kwargs obje olmalıdır. Örnek args: [50], kwargs: {\"force\": true}",
            "fields": ("args", "kwargs")
        }),
        ("Son çalışma", {
            "fields": ("last_run_at", "last_task_id", "last_error")
        }),
        ("Zaman", {
            "fields": ("created_at", "updated_at")
        }),
    )

    @admin.display(description="Periyot")
    def interval_display(self, obj):
        return f"{obj.interval_every} {obj.get_interval_period_display()}"

    @admin.display(description="Son hata")
    def last_error_short(self, obj):
        if not obj.last_error:
            return "-"
        return obj.last_error[:90]


@admin.register(OctoTaskRule)
class OctoTaskRuleAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("code", "module", "severity", "title_tr", "priority_score", "is_active", "updated_at")
    list_filter = ("module", "severity", "is_active")
    search_fields = ("code", "title_tr", "message_tr", "condition_key", "source_platform", "source_table")
    readonly_fields = ("created_at", "updated_at")
    actions = (export_selected_as_csv, queue_octo_task_generation, mark_selected_active, mark_selected_inactive)
    fieldsets = (
        ("Görev tanımı", {
            "fields": ("code", "module", "severity", "priority_score", "is_active")
        }),
        ("Türkçe içerik", {
            "fields": ("title_tr", "message_tr", "action_text_tr", "cta_text")
        }),
        ("İngilizce içerik", {
            "classes": ("collapse",),
            "fields": ("title_en", "message_en", "action_text_en")
        }),
        ("Koşul ve kaynak", {
            "fields": ("condition_key", "condition_description", "user_condition", "source_platform", "source_table")
        }),
        ("Analiz açıklaması", {
            "fields": ("root_cause", "expected_result")
        }),
        ("Zaman", {
            "fields": ("created_at", "updated_at")
        }),
    )


@admin.register(OctoTaskInstance)
class OctoTaskInstanceAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("title_tr", "user", "module", "severity", "status_badge", "priority_score", "platform_account", "campaign", "last_detected_at")
    list_filter = ("status", "severity", "module", "last_detected_at", "created_at")
    search_fields = ("title_tr", "message_tr", "unique_key", "user__email", "user__username", "platform_account__account_name", "campaign__name")
    autocomplete_fields = ("rule", "user", "platform_connection", "platform_account", "campaign", "ad_group", "ad", "creative")
    readonly_fields = ("created_at", "updated_at", "first_detected_at", "last_detected_at", "completed_at", "dismissed_at")
    date_hierarchy = "last_detected_at"
    actions = (export_selected_as_csv, mark_octo_tasks_done, dismiss_octo_tasks, reopen_octo_tasks)


@admin.register(OctoTaskActionLog)
class OctoTaskActionLogAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("task", "user", "action", "note", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("task__title_tr", "user__email", "user__username", "note")
    autocomplete_fields = ("task", "user")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"


@admin.register(OctoRuleEngineRun)
class OctoRuleEngineRunAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = (
        "user", "platform_account", "trigger", "status", "active_rule_count",
        "campaigns_evaluated", "signals_matched", "tasks_created", "started_at", "finished_at",
    )
    list_filter = ("status", "trigger", "started_at")
    search_fields = (
        "user__username", "user__email", "platform_account__account_name",
        "celery_task_id", "error_message",
    )
    readonly_fields = (
        "user", "platform_account", "trigger", "status", "celery_task_id",
        "active_rule_count", "campaigns_evaluated", "signals_matched",
        "tasks_created", "tasks_skipped", "details", "error_message",
        "started_at", "finished_at", "created_at",
    )
    date_hierarchy = "started_at"


@admin.register(SystemErrorLog)
class SystemErrorLogAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("error_id", "short_message", "severity", "status_badge", "user", "file_name", "line_number", "created_at")
    list_filter = ("severity", "status", "method", "created_at")
    search_fields = ("error_id", "message", "traceback", "file_name", "function_name", "url", "user__email", "user__username")
    autocomplete_fields = ("user", "resolved_by")
    readonly_fields = ("error_id", "created_at", "updated_at")
    date_hierarchy = "created_at"
    actions = (export_selected_as_csv, resolve_system_errors)


@admin.register(Notification)
class NotificationAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("title", "user", "level", "is_read", "created_at")
    list_filter = ("level", "is_read", "created_at")
    search_fields = ("title", "message", "user__email", "user__username")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    actions = (export_selected_as_csv, mark_notifications_read)


@admin.register(CampaignOctoAnalysis)
class CampaignOctoAnalysisAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("campaign_name", "user", "platform_name", "octo_score", "analysis_score", "status_badge", "risk_level", "roas", "ctr", "spend", "created_at")
    list_filter = ("status", "risk_level", "success_level", "source", "created_at")
    search_fields = ("campaign_name", "platform_name", "account_name", "analysis_text", "recommendation_text", "user__email")
    autocomplete_fields = ("user", "campaign")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"


@admin.register(CampaignOctoRecommendation)
class CampaignOctoRecommendationAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("campaign_name", "user", "priority", "is_applied", "success_rate", "estimated_roas_gain", "outcome_status", "created_at")
    list_filter = ("priority", "is_applied", "outcome_status", "source", "created_at")
    search_fields = ("campaign_name", "summary", "recommendations", "expected_impact", "outcome_note", "user__email")
    autocomplete_fields = ("user", "campaign", "analysis", "applied_by")
    readonly_fields = ("created_at", "updated_at", "applied_at", "outcome_checked_at")
    date_hierarchy = "created_at"


@admin.register(Invoice)
class InvoiceAdmin(PaymentTotalsAdminMixin, ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("invoice_number", "user", "status", "is_paid", "total_amount", "payment_method", "due_date", "payment_date", "created_at")
    list_filter = ("status", "is_paid", "payment_method", "due_date", "created_at")
    search_fields = ("invoice_number", "user__email", "user__username", "description", "notes")
    autocomplete_fields = ("user", "subscription", "billing_info")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
    payment_total_fields = (
        ("net", "KDV Hariç Toplam", ("amount",)),
        ("vat", "KDV Toplamı", ("kdv_amount",)),
        ("gross", "KDV Dahil Toplam", ("total_amount",)),
    )

    @admin.display(description="Toplam")
    def total_amount_display(self, obj):
        return _currency(getattr(obj, "total_amount", 0))


@admin.register(Payment)
class PaymentAdmin(PaymentTotalsAdminMixin, ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("user", "purchase", "billing_period", "payment_method", "status", "amount", "kdv_amount", "transaction_id", "created_at")
    list_filter = ("payment_method", "billing_period", "status", "created_at")
    search_fields = ("user__email", "user__username", "transaction_id", "notes")
    autocomplete_fields = ("user", "plan", "ai_credit_package", "product_research_package", "billing_info")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
    actions = ("approve_selected_bank_transfers", export_selected_as_csv)
    payment_total_fields = (
        ("net", "KDV Hariç Toplam", ("amount",)),
        ("vat", "KDV Toplamı", ("kdv_amount",)),
        ("gross", "KDV Dahil Toplam", ("amount", "kdv_amount")),
    )

    @admin.display(description="Satın alınan")
    def purchase(self, obj):
        return obj.purchase_label

    @admin.action(description="Seçili havale/EFT ödemelerini onayla ve satın alımı tamamla")
    def approve_selected_bank_transfers(self, request, queryset):
        from core.services.bank_transfer_approval import approve_bank_transfer_payment

        approved = 0
        skipped = 0
        for payment in queryset:
            result = approve_bank_transfer_payment(
                payment,
                approved_by=request.user,
                note=f"Admin onayi: {request.user.get_username()}",
            )
            if result.get("approved"):
                approved += 1
            else:
                skipped += 1
        if approved:
            self.message_user(request, f"{approved} havale/EFT ödemesi onaylandı; satın alım ve fatura tamamlandı.", messages.SUCCESS)
        if skipped:
            self.message_user(request, f"{skipped} ödeme atlandı. Yalnızca bekleyen ve ürünü tanımlı havale/EFT ödemeleri onaylanır.", messages.WARNING)


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(PaymentTotalsAdminMixin, ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("user", "payment", "transaction_type", "status", "amount", "reference_id", "created_at")
    list_filter = ("transaction_type", "status", "created_at")
    search_fields = ("reference_id", "notes", "user__email", "user__username")
    autocomplete_fields = ("user", "payment")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    payment_total_fields = (
        ("amount", "İşlem Tutarı Toplamı", ("amount",)),
    )


@admin.register(BillingInfo)
class BillingInfoAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("user", "customer_type", "company_name", "tax_number", "city", "district", "created_at")
    search_fields = ("user__email", "user__username", "company_name", "tax_number", "city", "district", "email", "phone")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)


@admin.register(ContactMessage)
class ContactMessageAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("name", "email", "subject", "is_read", "created_at")
    list_filter = ("is_read", "created_at")
    search_fields = ("name", "email", "subject", "message")
    readonly_fields = ("name", "email", "subject", "message", "created_at")
    date_hierarchy = "created_at"
    actions = ("mark_as_read", "mark_as_unread", export_selected_as_csv)

    @admin.action(description="Seçili mesajları okundu yap")
    def mark_as_read(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_read=True)} mesaj okundu işaretlendi.", messages.SUCCESS)

    @admin.action(description="Seçili mesajları okunmadı yap")
    def mark_as_unread(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_read=False)} mesaj okunmadı işaretlendi.", messages.SUCCESS)


@admin.register(DemoRequest)
class DemoRequestAdmin(ProfessionalAdminMixin, admin.ModelAdmin):
    list_display = ("company", "name", "email", "phone", "goal", "is_read", "handled_by", "created_at")
    list_filter = ("is_read", "ad_spend", "created_at")
    search_fields = ("company", "name", "email", "phone", "goal", "message")
    readonly_fields = ("name", "email", "phone", "company", "role", "ad_spend", "platforms", "goal", "message", "created_at", "handled_at")
    autocomplete_fields = ("handled_by",)
    date_hierarchy = "created_at"
    actions = ("mark_as_read", "mark_as_unread", "assign_to_me", export_selected_as_csv)

    @admin.action(description="Seçili demo taleplerini okundu yap")
    def mark_as_read(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_read=True)} demo talebi okundu işaretlendi.", messages.SUCCESS)

    @admin.action(description="Seçili demo taleplerini okunmadı yap")
    def mark_as_unread(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_read=False)} demo talebi okunmadı işaretlendi.", messages.SUCCESS)

    @admin.action(description="Seçili demo taleplerini bana ata")
    def assign_to_me(self, request, queryset):
        updated = queryset.update(handled_by=request.user, handled_at=timezone.now(), is_read=True)
        self.message_user(request, f"{updated} demo talebi size atandı.", messages.SUCCESS)


for model in [
    Competitor, OctoTaskRule, OctoTaskInstance, OctoTaskActionLog,
    InstagramAccount, InstagramMedia, InstagramInsight, InstagramPostQueue,
    AdCampaign, AdMetric, AIAnalysis, ReklamAIAnaliz, Report,
    ControlTowerSnapshot, ControlTowerCardSnapshot, ControlTowerAIAnalysis,
    ControlTowerActionItem, ControlTowerDecision, AudienceHistory, PlacementHistory,
]:
    safe_register(model, EnhancedAutoAdmin)


for model in apps.get_app_config("core").get_models():
    safe_register(model, EnhancedAutoAdmin)


_original_admin_get_urls = admin.site.get_urls


def _professional_admin_urls():
    custom_urls = [
        path(
            "logout/",
            admin_logout_view,
            name="logout",
        ),
        path(
            "ai-kontor-raporu/",
            staff_member_required(ai_credit_report_view),
            name="ai_credit_report",
        ),
        path(
            "ucretsiz-deneme-raporu/",
            staff_member_required(free_trial_report_view),
            name="free_trial_report",
        ),
        path(
            "ai-kontor-openai-yenile/",
            staff_member_required(sync_openai_usage_admin_view),
            name="sync_openai_usage",
        ),
        path(
            "ai-kontor-raporu/uye/<int:object_id>/",
            staff_member_required(lambda request, object_id: ai_credit_statement_view(request, "user", object_id)),
            name="ai_credit_report_user",
        ),
        path(
            "ai-kontor-raporu/ajans/<int:object_id>/",
            staff_member_required(lambda request, object_id: ai_credit_statement_view(request, "organization", object_id)),
            name="ai_credit_report_organization",
        ),
        path(
            "celery-gorevleri/",
            staff_member_required(celery_tasks_view),
            name="celery_tasks",
        ),
        path(
            "guvenlik-giris-ayarlari/",
            staff_member_required(auth_security_view),
            name="auth_security",
        ),
    ]
    return custom_urls + _original_admin_get_urls()


admin.site.get_urls = _professional_admin_urls
