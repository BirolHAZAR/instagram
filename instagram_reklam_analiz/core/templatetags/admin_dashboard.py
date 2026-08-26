from decimal import Decimal

from django import template
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Count, Sum
from django.utils import timezone

from core.models import (
    Ad,
    AdMetricHistory,
    AgencyClient,
    AICreditLedger,
    ActivityLog,
    Campaign,
    CampaignOctoAnalysis,
    ContactMessage,
    DemoRequest,
    MarketplaceAccount,
    MarketplaceListing,
    MarketplaceSyncRun,
    OctoTaskActionLog,
    OctoTaskInstance,
    Notification,
    Organization,
    Payment,
    PlatformConnection,
    PlatformAccount,
    PlatformSyncJob,
    Product,
    ReferralCode,
    ReferralProgramRule,
    ReferralProgramSetting,
    ReferralReward,
    SaaSAICreditPool,
    SystemErrorLog,
    UserSubscription,
)
from core.services.entitlements import get_ai_credit_balance, get_saas_ai_credit_cycle, get_subscription_credit_cycle

register = template.Library()


def _format_tr_decimal(value):
    try:
        number = Decimal(str(value or 0))
    except Exception:
        number = Decimal("0")
    formatted = f"{number:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _format_tr_int(value):
    try:
        number = int(Decimal(str(value or 0)))
    except Exception:
        number = 0
    return f"{number:,}".replace(",", ".")


@register.filter
def tr_decimal(value):
    return _format_tr_decimal(value)


@register.filter
def tr_int(value):
    return _format_tr_int(value)


@register.filter
def tr_percent(value):
    return f"%{_format_tr_decimal(value)}"


def _count(queryset, default=0):
    try:
        return queryset.count()
    except Exception:
        return default


def _sum(queryset, field_name):
    try:
        value = queryset.aggregate(total=Sum(field_name))["total"]
    except Exception:
        value = None
    return value or Decimal("0")


def _int_sum(queryset, field_name):
    try:
        value = queryset.aggregate(total=Sum(field_name))["total"]
    except Exception:
        value = None
    return int(value or 0)


def _group_counts(queryset, field_name, limit=6):
    try:
        return list(
            queryset.values(field_name)
            .annotate(total=Count("id"))
            .order_by("-total")[:limit]
        )
    except Exception:
        return []


def _money(value):
    return f"{_format_tr_decimal(value)} TL"


def _payment_bucket(queryset):
    net = _sum(queryset, "amount")
    vat = _sum(queryset, "kdv_amount")
    return {
        "net": _money(net),
        "vat": _money(vat),
        "gross": _money(net + vat),
        "count": _count(queryset),
    }


def _table_exists(model):
    try:
        return model._meta.db_table in connection.introspection.table_names()
    except Exception:
        return False


def _current_saas_credit_pool(today):
    cycle_start, cycle_end = get_saas_ai_credit_cycle(today)
    fallback = {
        "month": cycle_start,
        "period_label": f"{cycle_start:%d.%m.%Y} - {cycle_end:%d.%m.%Y}",
        "purchased": 0,
        "used": 0,
        "remaining": 0,
        "usage_percent": 0,
        "provider": "",
        "exists": False,
    }
    if not _table_exists(SaaSAICreditPool):
        return fallback
    try:
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
            "purchased": int(pool.purchased_credits or 0),
            "used": int(pool.used_credits or 0),
            "remaining": pool.remaining_credits,
            "usage_percent": pool.usage_percent,
            "provider": pool.provider_name,
            "note": pool.note,
            "updated_at": pool.updated_at,
            "exists": True,
        }
    except Exception:
        return fallback


def _credit_rows(queryset, group_field, label_field, limit=10):
    try:
        rows = list(
            queryset.values(group_field, label_field)
            .annotate(
                loaded=Sum("amount", filter=None),
            )
            .order_by(label_field)[:200]
        )
    except Exception:
        return []

    grouped = {}
    for row in rows:
        key = row[group_field]
        if key not in grouped:
            grouped[key] = {
                "label": row.get(label_field) or "Bilinmiyor",
                "loaded": 0,
                "used": 0,
                "balance": 0,
            }

    try:
        ledger_rows = queryset.values(group_field, label_field, "amount").order_by(group_field, "created_at", "id")
        for item in ledger_rows:
            key = item[group_field]
            data = grouped.setdefault(
                key,
                {"label": item.get(label_field) or "Bilinmiyor", "loaded": 0, "used": 0, "balance": 0},
            )
            amount = int(item["amount"] or 0)
            if amount >= 0:
                data["loaded"] += amount
            else:
                data["used"] += abs(amount)
            data["balance"] += amount
    except Exception:
        return []

    return sorted(grouped.values(), key=lambda row: row["used"], reverse=True)[:limit]


def _recent_credit_usage(limit=12):
    try:
        return list(
            AICreditLedger.objects
            .filter(amount__lt=0)
            .select_related("user", "organization")
            .order_by("-created_at", "-id")
            .values(
                "created_at",
                "user__email",
                "organization__name",
                "action",
                "amount",
                "balance_after",
                "reference",
                "note",
            )[:limit]
        )
    except Exception:
        return []


def _credit_totals(rows):
    return {
        "loaded": sum(int(row.get("loaded") or 0) for row in rows),
        "used": sum(int(row.get("used") or 0) for row in rows),
        "balance": sum(int(row.get("balance") or 0) for row in rows),
    }


def _active_subscription_credit_rows(subscriptions, limit=10):
    rows = []
    for subscription in subscriptions.select_related("user", "plan", "organization"):
        user = subscription.user
        cycle_start, cycle_end = get_subscription_credit_cycle(subscription, today=timezone.localdate())
        qs = AICreditLedger.objects.filter(
            user=user,
            created_at__date__gte=cycle_start,
            created_at__date__lt=cycle_end,
        )
        loaded = int(getattr(subscription.plan, "ai_credits_per_month", 0) or 0)
        topups = _int_sum(
            qs.filter(
                action__in=[
                    AICreditLedger.ACTION_PURCHASE,
                    AICreditLedger.ACTION_REFUND,
                    AICreditLedger.ACTION_ADJUSTMENT,
                ],
                amount__gt=0,
            ),
            "amount",
        )
        used = abs(_int_sum(qs.filter(action=AICreditLedger.ACTION_CONSUME, amount__lt=0), "amount"))
        rows.append({
            "label": user.email or user.username,
            "loaded": loaded + topups,
            "used": used,
            "balance": get_ai_credit_balance(user, organization=subscription.organization),
        })
    return sorted(rows, key=lambda row: row["used"], reverse=True)[:limit]


@register.simple_tag
def admin_dashboard_metrics():
    User = get_user_model()
    today = timezone.localdate()
    now = timezone.now()
    last_7_days = today - timezone.timedelta(days=7)
    last_30_days = today - timezone.timedelta(days=30)
    next_15_days = today + timezone.timedelta(days=15)
    current_week_start = today - timezone.timedelta(days=today.weekday())
    current_month_start = today.replace(day=1)

    active_subscriptions = UserSubscription.objects.filter(
        is_active=True,
        end_date__gte=today,
    )
    completed_payments = Payment.objects.filter(status="completed")
    recent_ad_metrics = AdMetricHistory.objects.filter(date__gte=last_30_days)

    spend_30d = _sum(recent_ad_metrics, "spend")
    conversion_value_30d = _sum(recent_ad_metrics, "conversion_value")
    roas_30d = Decimal("0")
    if spend_30d:
        roas_30d = conversion_value_30d / spend_30d

    sync_runs = MarketplaceSyncRun.objects.all()
    platform_jobs = PlatformSyncJob.objects.all()
    critical_errors = SystemErrorLog.objects.filter(status__in=["new", "investigating"])
    credit_ledger = AICreditLedger.objects.all()
    credits_loaded = _int_sum(credit_ledger.filter(amount__gt=0), "amount")
    credits_used = abs(_int_sum(credit_ledger.filter(amount__lt=0), "amount"))
    credits_remaining = credits_loaded - credits_used
    open_tasks = OctoTaskInstance.objects.filter(status__in=["open", "viewed", "snoozed"])
    today_tasks = OctoTaskInstance.objects.filter(created_at__date=today)
    hourly_task_actions = OctoTaskActionLog.objects.filter(created_at__gte=now - timezone.timedelta(hours=1))
    expiring_subscriptions = active_subscriptions.filter(end_date__lte=next_15_days)
    expired_subscriptions = UserSubscription.objects.filter(is_active=True, end_date__lt=today)
    token_expiring = PlatformConnection.objects.filter(token_expiry__date__gte=today, token_expiry__date__lte=next_15_days)
    token_expired = PlatformConnection.objects.filter(token_expiry__lt=now)
    saas_credit_pool = _current_saas_credit_pool(today)
    credit_top_users = _active_subscription_credit_rows(active_subscriptions)
    credit_top_organizations = _credit_rows(credit_ledger.exclude(organization=None), "organization_id", "organization__name")
    monthly_credit_totals = _credit_totals(credit_top_users)
    credits_loaded = monthly_credit_totals["loaded"]
    credits_used = monthly_credit_totals["used"]
    credits_remaining = monthly_credit_totals["balance"]
    expiring_rows = list(
        expiring_subscriptions.select_related("user", "plan", "organization")
        .order_by("end_date")
        .values("user__email", "plan__display_name", "organization__name", "end_date")[:10]
    )
    recent_credit_usage = _recent_credit_usage()
    try:
        referral_settings = ReferralProgramSetting.current()
        referrals_enabled = referral_settings.is_enabled
    except Exception:
        referrals_enabled = False
    referral_rewards = ReferralReward.objects.all()

    return {
        "generated_at": timezone.now(),
        "summary_cards": [
            {
                "label": "SaaS aylık AI kontör",
                "value": _format_tr_int(saas_credit_pool["remaining"]),
                "hint": f"Alınan {_format_tr_int(saas_credit_pool['purchased'])} / kullanılan {_format_tr_int(saas_credit_pool['used'])}",
                "tone": "indigo",
            },
            {
                "label": "Bugünkü ödeme",
                "value": _payment_bucket(completed_payments.filter(created_at__date=today))["gross"],
                "hint": "KDV dahil tahsilat",
                "tone": "green",
            },
            {
                "label": "Bugünkü yeni üye",
                "value": _format_tr_int(_count(User.objects.filter(date_joined__date=today))),
                "hint": f"Bu ay: {_format_tr_int(_count(User.objects.filter(date_joined__date__gte=current_month_start)))}",
                "tone": "blue",
            },
            {
                "label": "Bugünkü kontör kullanımı",
                "value": _format_tr_int(abs(_int_sum(credit_ledger.filter(amount__lt=0, created_at__date=today), "amount"))),
                "hint": f"Bu ay: {_format_tr_int(abs(_int_sum(credit_ledger.filter(amount__lt=0, created_at__date__gte=current_month_start), 'amount')))}",
                "tone": "amber",
            },
            {
                "label": "Kullanicilar",
                "value": _format_tr_int(_count(User.objects.all())),
                "hint": f"Son 7 gun yeni: {_format_tr_int(_count(User.objects.filter(date_joined__date__gte=last_7_days)))}",
                "tone": "blue",
            },
            {
                "label": "Aktif abonelik",
                "value": _format_tr_int(_count(active_subscriptions)),
                "hint": f"Organizasyon: {_format_tr_int(_count(Organization.objects.filter(is_active=True)))}",
                "tone": "green",
            },
            {
                "label": "Aylik gelir",
                "value": f"{_sum(completed_payments.filter(created_at__date__gte=last_30_days), 'amount'):,.2f} TL",
                "hint": f"Basarili odeme: {_count(completed_payments)}",
                "tone": "amber",
            },
            {
                "label": "Aktif kampanya",
                "value": _format_tr_int(_count(Campaign.objects.filter(is_active=True))),
                "hint": f"Aktif reklam: {_format_tr_int(_count(Ad.objects.filter(is_active=True)))}",
                "tone": "indigo",
            },
            {
                "label": "30 gun ROAS",
                "value": f"{roas_30d:.2f}",
                "hint": f"Harcama: {spend_30d:,.2f} TL",
                "tone": "purple",
            },
            {
                "label": "Kritik isler",
                "value": _format_tr_int(_count(critical_errors.filter(severity__in=["critical", "error"]))),
                "hint": f"Okunmamis bildirim: {_format_tr_int(_count(Notification.objects.filter(is_read=False)))}",
                "tone": "red",
            },
            {
                "label": "AI kontör",
                "value": _format_tr_int(credits_remaining),
                "hint": f"Toplam {_format_tr_int(credits_loaded)} / kullanılan {_format_tr_int(credits_used)}",
                "tone": "green",
            },
            {
                "label": "Açık görev",
                "value": _format_tr_int(_count(open_tasks)),
                "hint": f"Bugün yeni: {_format_tr_int(_count(today_tasks))}",
                "tone": "blue",
            },
            {
                "label": "15 gün üyelik",
                "value": _format_tr_int(_count(expiring_subscriptions)),
                "hint": f"Süresi geçen aktif: {_format_tr_int(_count(expired_subscriptions))}",
                "tone": "amber",
            },
            {
                "label": "Token riski",
                "value": _format_tr_int(_count(token_expired)),
                "hint": f"15 günde dolacak: {_format_tr_int(_count(token_expiring))}",
                "tone": "red",
            },
        ],
        "credits": {
            "total_label": f"Toplam kontor sayisi {_format_tr_int(credits_loaded)}",
            "used_label": f"Kullanilan {_format_tr_int(credits_used)}",
            "remaining_label": f"Kalan {_format_tr_int(credits_remaining)}",
            "loaded": credits_loaded,
            "used": credits_used,
            "remaining": credits_remaining,
            "purchases": _int_sum(credit_ledger.filter(action="purchase"), "amount"),
            "plan_grants": _int_sum(credit_ledger.filter(action="grant"), "amount"),
            "adjustments": _int_sum(credit_ledger.filter(action="adjustment"), "amount"),
            "usage_today": abs(_int_sum(credit_ledger.filter(amount__lt=0, created_at__date=today), "amount")),
            "usage_week": abs(_int_sum(credit_ledger.filter(amount__lt=0, created_at__date__gte=current_week_start), "amount")),
            "usage_month": abs(_int_sum(credit_ledger.filter(amount__lt=0, created_at__date__gte=current_month_start), "amount")),
            "top_users": credit_top_users,
            "top_users_totals": _credit_totals(credit_top_users),
            "top_organizations": credit_top_organizations,
            "top_organizations_totals": _credit_totals(credit_top_organizations),
            "recent_usage": recent_credit_usage,
            "recent_usage_totals": {
                "amount": sum(abs(int(row.get("amount") or 0)) for row in recent_credit_usage),
            },
        },
        "saas_credit_pool": saas_credit_pool,
        "payments": {
            "today": _payment_bucket(completed_payments.filter(created_at__date=today)),
            "week": _payment_bucket(completed_payments.filter(created_at__date__gte=current_week_start)),
            "month": _payment_bucket(completed_payments.filter(created_at__date__gte=current_month_start)),
            "total": _payment_bucket(completed_payments),
            "pending_count": _count(Payment.objects.filter(status="pending")),
            "failed_count": _count(Payment.objects.filter(status="failed")),
            "by_status": _group_counts(Payment.objects.all(), "status"),
        },
        "memberships": {
            "new_today": _count(User.objects.filter(date_joined__date=today)),
            "new_week": _count(User.objects.filter(date_joined__date__gte=current_week_start)),
            "new_month": _count(User.objects.filter(date_joined__date__gte=current_month_start)),
            "expiring_15": _count(expiring_subscriptions),
            "expired_active": _count(expired_subscriptions),
            "active_by_plan": _group_counts(active_subscriptions, "plan__display_name", limit=10),
            "expiring_rows": expiring_rows,
            "expiring_rows_total": len(expiring_rows),
        },
        "referrals": {
            "enabled": referrals_enabled,
            "active_rules": _count(ReferralProgramRule.objects.filter(is_active=True)),
            "codes": _count(ReferralCode.objects.all()),
            "active_codes": _count(ReferralCode.objects.filter(is_active=True)),
            "pending": _count(referral_rewards.filter(status=ReferralReward.STATUS_PENDING)),
            "awarded": _count(referral_rewards.filter(status=ReferralReward.STATUS_AWARDED)),
            "cancelled": _count(referral_rewards.filter(status=ReferralReward.STATUS_CANCELLED)),
            "awarded_amount": _int_sum(
                referral_rewards.filter(
                    status=ReferralReward.STATUS_AWARDED,
                    reward_type=ReferralCode.REWARD_AI_CREDITS,
                ),
                "reward_amount",
            ),
            "recent": list(
                referral_rewards.select_related("referral_code", "referrer", "referred_user")
                .order_by("-created_at")
                .values(
                    "created_at",
                    "referral_code__code",
                    "referrer__email",
                    "referred_user__email",
                    "reward_amount",
                    "reward_type",
                    "status",
                )[:8]
            ),
        },
        "tasks": {
            "open": _count(open_tasks),
            "today": _count(today_tasks),
            "hour_actions": _count(hourly_task_actions),
            "daily_actions": _count(OctoTaskActionLog.objects.filter(created_at__date=today)),
            "by_status": _group_counts(OctoTaskInstance.objects.all(), "status"),
            "by_severity": _group_counts(OctoTaskInstance.objects.all(), "severity"),
            "by_module": _group_counts(OctoTaskInstance.objects.all(), "module"),
            "recent": list(
                OctoTaskInstance.objects.select_related("user", "platform_account")
                .order_by("-last_detected_at")
                .values("id", "title_tr", "user__email", "severity", "status", "last_detected_at")[:8]
            ),
        },
        "tokens": {
            "active_connections": _count(PlatformConnection.objects.filter(is_active=True)),
            "expired": _count(token_expired),
            "expiring_15": _count(token_expiring),
            "by_status": _group_counts(PlatformConnection.objects.all(), "status"),
            "expiring_rows": list(
                PlatformConnection.objects.select_related("user", "platform")
                .filter(token_expiry__isnull=False)
                .order_by("token_expiry")
                .values("user__email", "platform__name", "name", "status", "token_expiry")[:10]
            ),
        },
        "logs": {
            "errors_today": _count(SystemErrorLog.objects.filter(created_at__date=today)),
            "critical_open": _count(critical_errors.filter(severity="critical")),
            "activity_today": _count(ActivityLog.objects.filter(created_at__date=today)),
            "error_by_severity": _group_counts(SystemErrorLog.objects.all(), "severity"),
            "error_by_status": _group_counts(SystemErrorLog.objects.all(), "status"),
        },
        "operations": {
            "platform_accounts": _count(PlatformAccount.objects.filter(is_active=True)),
            "marketplace_accounts": _count(MarketplaceAccount.objects.filter(is_active=True)),
            "products": _count(Product.objects.filter(is_active=True)),
            "listings": _count(MarketplaceListing.objects.all()),
            "agency_clients": _count(AgencyClient.objects.filter(is_active=True)),
        },
        "leads": {
            "unread_contacts": _count(ContactMessage.objects.filter(is_read=False)),
            "total_contacts": _count(ContactMessage.objects.all()),
            "unread_demo_requests": _count(DemoRequest.objects.filter(is_read=False)),
            "total_demo_requests": _count(DemoRequest.objects.all()),
            "recent_demo_requests": list(
                DemoRequest.objects.order_by("-created_at")
                .values("company", "name", "email", "phone", "goal", "is_read", "created_at")[:8]
            ),
            "recent_contacts": list(
                ContactMessage.objects.order_by("-created_at")
                .values("name", "email", "subject", "is_read", "created_at")[:8]
            ),
        },
        "sync": {
            "marketplace_status": _group_counts(sync_runs, "status"),
            "platform_status": _group_counts(platform_jobs, "status"),
            "marketplace_recent_failures": _count(sync_runs.filter(status="failed", created_at__date__gte=last_7_days)),
            "platform_recent_failures": _count(platform_jobs.filter(status="failed", created_at__date__gte=last_7_days)),
        },
        "octo": {
            "risk": _group_counts(CampaignOctoAnalysis.objects.all(), "risk_level"),
            "status": _group_counts(CampaignOctoAnalysis.objects.all(), "status"),
            "critical": _count(CampaignOctoAnalysis.objects.filter(risk_level__in=["high", "critical"])),
        },
        "quick_links": [
            ("Kampanyalar", "/admin/core/campaign/"),
            ("Reklam performansi", "/admin/core/admetrichistory/"),
            ("Platform senkronlari", "/admin/core/platformsyncjob/"),
            ("Pazar yeri urunleri", "/admin/core/product/"),
            ("Urun arastirma kayitlari", "/admin/core/marketplaceproductresearch/"),
            ("Urun arastirma haklari", "/admin/core/userproductresearchbalance/"),
            ("Urun arastirma hareketleri", "/admin/core/productresearchledger/"),
            ("Urun arastirma paketleri", "/admin/core/productresearchpackage/"),
            ("Tavily API havuzu", "/admin/core/tavilyapipool/"),
            ("Tavily API kullanimi", "/admin/core/tavilyapiusageledger/"),
            ("Faturalar", "/admin/core/invoice/"),
            ("Odemeler", "/admin/core/payment/"),
            ("Demo talepleri", "/admin/core/demorequest/"),
            ("Iletisim mesajlari", "/admin/core/contactmessage/"),
            ("Referans ayarlari", "/admin/core/referralprogramsetting/"),
            ("Referans kurallari", "/admin/core/referralprogramrule/"),
            ("Promosyon kodlari", "/admin/core/referralcode/"),
            ("Referans haklari", "/admin/core/referralreward/"),
            ("Sistem hatalari", "/admin/core/systemerrorlog/"),
            ("Ücretsiz deneme raporu", "/admin/ucretsiz-deneme-raporu/"),
            ("AI kontör raporu", "/admin/ai-kontor-raporu/"),
            ("Celery gorevleri", "/admin/celery-gorevleri/"),
            ("Guvenlik ve sosyal giris", "/admin/guvenlik-giris-ayarlari/"),
            ("Admin periyodik gorevleri", "/admin/core/adminmanagedceleryschedule/"),
            ("Octo gorevleri", "/admin/core/octotaskinstance/"),
            ("Gorev kurallari", "/admin/core/octotaskrule/"),
            ("Token baglantilari", "/admin/core/platformconnection/"),
            ("Aktivite loglari", "/admin/core/activitylog/"),
        ],
    }
