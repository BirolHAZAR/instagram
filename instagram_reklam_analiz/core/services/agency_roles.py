from core.models import AgencyRoleGroup
from core.services.agency_permission_matrix import all_agency_menu_permission_keys


READ_ONLY_MENU_KEYS = {
    "control_tower",
    "executive_dashboard",
    "notification_center",
    "campaign_center",
    "campaign_panel",
    "adgroup_center",
    "reklam_panel",
    "reklam_hareketleri",
    "reklam_raporu",
    "health_center",
    "creative_center",
    "optimization_history",
    "organic_content_center",
    "competitor_intelligence",
    "rakip_reklam_paneli",
    "rakip_reklam_hareketleri",
    "rakip_reklam_karsilastirma",
    "performance_center",
    "reports_center",
    "reklam_karsilastirma",
    "reklam_tarihcesi",
    "daily_budget_report",
    "google_analytics_center",
    "agency_dashboard",
    "notification_center",
    "fihrist",
    "my_account",
}

EDITOR_MENU_KEYS = READ_ONLY_MENU_KEYS | {
    "octo_task_center",
    "campaign_octo_recommendations",
    "apply_rules_to_campaigns",
    "optimizasyon_kurallari",
    "organic_content_composer",
    "creative_studio",
    "rakip_ekle",
    "ai_dashboard",
    "anomaly_dashboard",
    "ai_campaign_analysis",
    "ai_recommendations",
    "scheduled_reports",
}


def default_agency_role_groups():
    all_keys = set(all_agency_menu_permission_keys())
    return {
        "admin": {
            "name": "Admin",
            "description": "Müşteri, hesap, rakip, rapor ve kullanıcı yönetimi.",
            "can_manage_clients": True,
            "can_manage_accounts": True,
            "can_manage_competitors": True,
            "can_view_reports": True,
            "can_manage_members": True,
            "can_manage_billing": False,
            "menu_permissions": sorted(all_keys - {"my_subscriptions", "my_invoices"}),
        },
        "editor": {
            "name": "Editör",
            "description": "Operasyonları yönetir; kullanıcı ve fatura ayarlarını değiştiremez.",
            "can_manage_clients": True,
            "can_manage_accounts": True,
            "can_manage_competitors": True,
            "can_view_reports": True,
            "can_manage_members": False,
            "can_manage_billing": False,
            "menu_permissions": sorted(EDITOR_MENU_KEYS & all_keys),
        },
        "viewer": {
            "name": "İzleyici",
            "description": "Verileri ve raporları görüntüler; yönetim işlemi yapamaz.",
            "can_manage_clients": False,
            "can_manage_accounts": False,
            "can_manage_competitors": False,
            "can_view_reports": True,
            "can_manage_members": False,
            "can_manage_billing": False,
            "menu_permissions": sorted(READ_ONLY_MENU_KEYS & all_keys),
        },
    }


def ensure_default_agency_role_groups(organization):
    groups = {}
    for system_key, defaults in default_agency_role_groups().items():
        group, _ = AgencyRoleGroup.objects.get_or_create(
            organization=organization,
            system_key=system_key,
            defaults=defaults,
        )
        groups[system_key] = group
    return groups
