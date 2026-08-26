from django.http import HttpResponseForbidden

from core.services.agency_permission_matrix import (
    all_agency_menu_permission_keys,
    user_has_agency_menu_permission,
)


URL_PERMISSION_ALIASES = {
    "agency_dashboard_org": "agency_dashboard",
    "agency_members": "agency_members",
    "agency_member_invite": "agency_members",
    "agency_member_update": "agency_members",
    "agency_subaccount_delete": "agency_members",
    "agency_role_group_create": "agency_members",
    "agency_role_group_update": "agency_members",
    "agency_branding": "agency_branding",
    "agency_client_create": "agency_dashboard",
    "agency_client_detail": "agency_dashboard",
    "agency_client_assign_account": "agency_dashboard",
    "agency_platform_account_create": "hesap_ekle",
    "agency_client_platform_account_create": "hesap_ekle",
    "agency_competitor_create": "rakip_ekle",
    "generate_content_api": "creative_studio",
    "creative_reference_prompt": "creative_studio",
    "creative_publish": "creative_studio",
    "creative_templates": "creative_studio",
    "creative_project_detail": "creative_studio",
    "creative_update_variant_text": "creative_studio",
    "creative_regenerate_media": "creative_studio",
    "creative_competitors_by_platform": "creative_studio",
    "creative_competitor_ads": "creative_studio",
    "organic_content_refresh": "organic_content_center",
    "organic_content_sync_account": "organic_content_center",
    "organic_content_publish": "organic_content_center",
    "trigger_scan": "anomaly_dashboard",
    "trigger_anomaly_scan": "anomaly_dashboard",
    "trigger_scan_legacy": "anomaly_dashboard",
    "dismiss_alert": "anomaly_dashboard",
    "dismiss_anomaly_alert": "anomaly_dashboard",
    "mark_all_read": "anomaly_dashboard",
    "mark_all_alerts_read": "anomaly_dashboard",
    "take_opportunity": "anomaly_dashboard",
    "take_opportunity_action": "anomaly_dashboard",
    "anomaly_count": "anomaly_dashboard",
    "agency_client_platform_account_create": "agency_dashboard",
    "agency_competitor_create": "agency_dashboard",
    "report_list": "scheduled_reports",
    "generate_report": "scheduled_reports",
    "scheduled_report_edit": "scheduled_reports",
    "scheduled_report_delete": "scheduled_reports",
    "scheduled_report_toggle": "scheduled_reports",
    "scheduled_report_send_now": "scheduled_reports",
    "scheduled_report_preview": "scheduled_reports",
    "scheduled_report_preview_html": "scheduled_reports",
    "scheduled_report_pdf": "scheduled_reports",
    "marketplace_account_edit": "marketplace_accounts",
    "marketplace_account_test": "marketplace_accounts",
    "marketplace_account_delete": "marketplace_accounts",
}


class AgencyMenuPermissionMiddleware:
    """Restrict agency members by the module/link matrix.

    Non-agency users keep the normal product behavior. Agency owners, staff and
    superusers are allowed by the central permission helper.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.permission_keys = set(all_agency_menu_permission_keys())

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None

        resolver_match = getattr(request, "resolver_match", None)
        url_name = getattr(resolver_match, "url_name", None)
        permission_key = URL_PERMISSION_ALIASES.get(url_name, url_name)
        if permission_key not in self.permission_keys:
            return None

        if user_has_agency_menu_permission(user, permission_key):
            return None

        return HttpResponseForbidden("Bu modüle erişim yetkiniz yok.")
