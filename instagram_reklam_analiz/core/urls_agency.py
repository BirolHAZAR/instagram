from django.urls import path

from core.views import agency


urlpatterns = [
    path("agency/", agency.agency_dashboard, name="agency_dashboard"),
    path("agency/<int:organization_id>/", agency.agency_dashboard, name="agency_dashboard_org"),
    path("agency/<int:organization_id>/branding/", agency.agency_branding, name="agency_branding"),
    path("agency/<int:organization_id>/members/", agency.agency_members, name="agency_members"),
    path("agency/<int:organization_id>/members/invite/", agency.agency_member_invite, name="agency_member_invite"),
    path("agency/<int:organization_id>/members/<int:member_id>/", agency.agency_member_update, name="agency_member_update"),
    path("agency/<int:organization_id>/subaccounts/<int:member_id>/delete/", agency.agency_subaccount_delete, name="agency_subaccount_delete"),
    path("agency/<int:organization_id>/role-groups/new/", agency.agency_role_group_create, name="agency_role_group_create"),
    path("agency/<int:organization_id>/role-groups/<int:group_id>/", agency.agency_role_group_update, name="agency_role_group_update"),
    path("agency/<int:organization_id>/clients/new/", agency.agency_client_create, name="agency_client_create"),
    path("agency/<int:organization_id>/clients/<int:client_id>/", agency.agency_client_detail, name="agency_client_detail"),
    path("agency/<int:organization_id>/clients/<int:client_id>/assign-account/", agency.agency_client_assign_account, name="agency_client_assign_account"),
    path("agency/<int:organization_id>/accounts/new/", agency.agency_platform_account_create, name="agency_platform_account_create"),
    path("agency/<int:organization_id>/clients/<int:client_id>/accounts/new/", agency.agency_platform_account_create, name="agency_client_platform_account_create"),
    path("agency/<int:organization_id>/competitors/new/", agency.agency_competitor_create, name="agency_competitor_create"),
]
