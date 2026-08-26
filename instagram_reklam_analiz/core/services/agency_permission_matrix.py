AGENCY_MENU_PERMISSION_GROUPS = [
    {
        "key": "command",
        "label": "Komuta Merkezi",
        "items": [
            ("control_tower", "Kontrol Kulesi"),
            ("octo_task_center", "Octo Görev Merkezi"),
            ("campaign_octo_recommendations", "Octo Tavsiye Merkezi"),
            ("executive_dashboard", "Executive Dashboard"),
            ("notification_center", "Bildirim Merkezi"),
            ("activity_log", "Aktivite Geçmişi"),
        ],
    },
    {
        "key": "operations",
        "label": "Operasyonlar",
        "items": [
            ("campaign_center", "Kampanya Merkezi"),
            ("campaign_panel", "Kampanya Paneli"),
            ("adgroup_center", "Reklam Grubu Merkezi"),
            ("reklam_panel", "Reklam Paneli"),
            ("reklam_hareketleri", "Reklam Hareketleri"),
            ("reklam_raporu", "Reklam Raporu"),
            ("health_center", "Reklam Sağlık Merkezi"),
            ("creative_center", "Kreatif Merkezi"),
            ("apply_rules_to_campaigns", "Bütçe Optimizasyonu"),
            ("optimizasyon_kurallari", "Optimizasyon Kuralları"),
            ("optimization_history", "Optimizasyon Geçmişi"),
            ("marketplace_accounts", "Pazaryeri Hesap Bağlama"),
            ("marketplace_product_management", "Pazaryeri Ürün Yönetimi"),
            ("marketplace_product_research", "Pazaryeri Ürün Araştırması"),
            ("marketplace_price_tracking", "Pazaryeri Fiyat Takibi"),
            ("marketplace_price_history_report", "Pazaryeri Fiyat Geçmişi"),
        ],
    },
    {
        "key": "organic",
        "label": "Organik İçerik",
        "items": [
            ("organic_content_center", "İçerik Merkezi"),
            ("organic_content_composer", "İçerik Oluştur"),
            ("organic_connections", "Organik Bağlantılar"),
            ("creative_studio", "Creative Studio"),
        ],
    },
    {
        "key": "competition",
        "label": "Rekabet Merkezi",
        "items": [
            ("rakip_ekle", "Rakip Ekle"),
            ("competitor_intelligence", "Rakip İstihbaratı"),
            ("rakip_reklam_paneli", "Rakip Reklamları"),
            ("rakip_reklam_hareketleri", "Rakip Hareketleri"),
            ("rakip_reklam_karsilastirma", "Rakip Karşılaştırma"),
        ],
    },
    {
        "key": "ai",
        "label": "Octo AI",
        "items": [
            ("ai_dashboard", "AI Dashboard"),
            ("anomaly_dashboard", "Anomali Merkezi"),
            ("ai_campaign_analysis", "AI Kampanya Analizi"),
            ("ai_recommendations", "AI Öneriler"),
        ],
    },
    {
        "key": "analytics",
        "label": "Analiz Merkezi",
        "items": [
            ("performance_center", "Performans Merkezi"),
            ("reports_center", "Rapor Merkezi"),
            ("scheduled_reports", "Otomatik Raporlar"),
            ("reklam_karsilastirma", "Reklam Karşılaştırma"),
            ("reklam_tarihcesi", "Reklam Tarihçesi"),
            ("daily_budget_report", "Günlük Bütçe Raporu"),
        ],
    },
    {
        "key": "google_analytics",
        "label": "Google Analytics",
        "items": [
            ("google_analytics_center", "GA4 Genel Bakis"),
        ],
    },
    {
        "key": "system",
        "label": "Sistem ve Ajans",
        "items": [
            ("platform_connections", "Platform Bağlantıları"),
            ("hesap_ekle", "Hesap Ekle"),
            ("agency_dashboard", "Ajans Yönetimi"),
            ("agency_members", "Ajans Kullanıcıları"),
            ("agency_branding", "Logo & Rapor Markası"),
            ("update_notification_preferences", "Bildirim Tercihleri"),
            ("fihrist", "Reklam Fihristi"),
            ("my_account", "Hesabım"),
            ("my_subscriptions", "Abonelik"),
            ("my_invoices", "Faturalar"),
        ],
    },
]


AGENCY_MENU_PERMISSION_CHOICES = [
    (key, label)
    for group in AGENCY_MENU_PERMISSION_GROUPS
    for key, label in group["items"]
]


# Menu/view permissions backed by concrete MembershipPlan fields. Unlisted
# modules remain part of the base product and are controlled by subscription
# status plus (for agency members) the existing role matrix.
PLAN_PERMISSION_RULES = {
    "creative_studio": ("boolean", "has_ai_content_generation"),
    "organic_content_center": ("boolean", "has_content_calendar"),
    "organic_content_composer": ("boolean", "has_content_calendar"),
    "organic_connections": ("boolean", "has_content_calendar"),
    "scheduled_reports": ("boolean", "has_advanced_reporting"),
    "reports_center": ("boolean", "has_advanced_reporting"),
    "anomaly_dashboard": ("boolean", "has_opportunity_finder"),
    "rakip_ekle": ("positive", "max_competitors"),
    "competitor_intelligence": ("positive", "max_competitors"),
    "rakip_reklam_paneli": ("positive", "max_competitors"),
    "rakip_reklam_hareketleri": ("positive", "max_competitors"),
    "rakip_reklam_karsilastirma": ("positive", "max_competitors"),
    "marketplace_accounts": ("positive", "marketplace_product_research_per_month"),
    "marketplace_product_management": ("positive", "marketplace_product_research_per_month"),
    "marketplace_product_research": ("positive", "marketplace_product_research_per_month"),
    "marketplace_price_tracking": ("positive", "marketplace_price_check_per_month"),
    "marketplace_price_history_report": ("positive", "marketplace_price_check_per_month"),
    "agency_dashboard": ("boolean", "has_team_members"),
    "agency_members": ("boolean", "has_team_members"),
    "agency_branding": ("boolean", "has_white_label"),
}


def all_agency_menu_permission_keys():
    return [key for key, _label in AGENCY_MENU_PERMISSION_CHOICES]


def get_user_entitlement_plan(user):
    """Return the active personal or agency plan that grants this user's access."""
    if not user or not getattr(user, "is_authenticated", False):
        return None

    from django.db.models import Q
    from django.utils import timezone
    from core.models import Organization, OrganizationMember, UserSubscription

    organization_ids = set(
        Organization.objects.filter(owner=user, is_active=True).values_list("id", flat=True)
    )
    organization_ids.update(
        OrganizationMember.objects.filter(
            user=user, is_active=True, organization__is_active=True
        ).values_list("organization_id", flat=True)
    )
    scope = Q(user=user, organization__isnull=True)
    if organization_ids:
        scope |= Q(organization_id__in=organization_ids)
    subscription = (
        UserSubscription.objects.select_related("plan")
        .filter(scope, is_active=True, end_date__gte=timezone.localdate(), plan__is_active=True)
        .order_by("-plan__price", "-end_date")
        .first()
    )
    return subscription.plan if subscription else None


def user_has_plan_permission(user, permission_key):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return True
    rule = PLAN_PERMISSION_RULES.get(permission_key)
    if not rule:
        return True
    plan = get_user_entitlement_plan(user)
    if not plan:
        # Missing/expired subscriptions are handled centrally by
        # SubscriptionAccessMiddleware.
        return True
    if plan.name == "trial_14":
        return True
    rule_type, field_name = rule
    value = getattr(plan, field_name, False)
    return bool(value) if rule_type == "boolean" else int(value or 0) > 0


def user_has_agency_menu_permission(user, permission_key):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return True

    if not user_has_plan_permission(user, permission_key):
        return False

    from core.models import Organization, OrganizationMember

    if Organization.objects.filter(owner=user, is_active=True).exists():
        return True

    cache_attr = "_agency_menu_permission_cache"
    if not hasattr(user, cache_attr):
        membership = (
            OrganizationMember.objects.select_related("role_group").filter(
                user=user,
                is_active=True,
                organization__is_active=True,
            )
            .order_by("id")
            .first()
        )
        if not membership:
            setattr(user, cache_attr, None)
        else:
            allowed = set()
            if membership.role == OrganizationMember.ROLE_OWNER:
                allowed.update(all_agency_menu_permission_keys())
            if membership.role_group_id and membership.role_group.is_active:
                allowed.update(membership.role_group.menu_permissions or [])
            elif not membership.role_group_id:
                allowed.update(membership.menu_permissions or [])
            setattr(user, cache_attr, allowed)

    cached = getattr(user, cache_attr)
    if cached is None:
        return True

    return permission_key in cached
