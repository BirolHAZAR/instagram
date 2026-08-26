from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from core.forms import (
    AgencyClientForm,
    AgencyCompetitorForm,
    AgencyAccountAssignmentForm,
    AgencyRoleGroupForm,
    AgencyPlatformAccountForm,
    OrganizationMemberInviteForm,
    OrganizationMemberRoleForm,
    OrganizationBrandingForm,
)
from core.models import AgencyRoleGroup, AnalyticsProperty, AgencyClient, Competitor, Organization, OrganizationMember, Platform, PlatformAccount
from core.services.cache_service import CacheService
from core.services.agency_roles import ensure_default_agency_role_groups
from core.services.notification_helper import NotificationHelper
from core.views.hesap_ekle import PLATFORM_DEFAULTS, _save_verified_instagram_accounts, _save_verified_token_accounts
import requests


User = get_user_model()
AGENCY_DASHBOARD_CACHE_TIMEOUT = 180


def _invalidate_agency_cache(organization):
    if organization and organization.id:
        CacheService.bump_version("agency_dashboard", organization.id)


def _agency_organizations(user):
    owned = Q(owner=user)
    member = Q(members__user=user, members__is_active=True)
    return Organization.objects.filter(owned | member, is_active=True).distinct()


def _get_organization_for_user(user, organization_id=None):
    qs = _agency_organizations(user).select_related("active_plan")
    if organization_id:
        return get_object_or_404(qs, id=organization_id)
    organization = qs.order_by("name").first()
    if organization:
        return organization
    return Organization.objects.create(owner=user, name=f"{user.get_full_name() or user.email} Ajansı")


def _user_can_manage(organization, user):
    return _user_has_permission(organization, user, "manage_clients")


def _member_for(organization, user):
    if organization.owner_id == user.id:
        return OrganizationMember(
            organization=organization,
            user=user,
            role=OrganizationMember.ROLE_OWNER,
            is_active=True,
        )
    return organization.members.filter(user=user, is_active=True).first()


def _user_has_permission(organization, user, permission):
    member = _member_for(organization, user)
    return bool(member and member.has_permission(permission))


def _user_has_menu_permission(organization, user, permission_key):
    member = _member_for(organization, user)
    return bool(member and member.has_menu_permission(permission_key))


@login_required
def agency_dashboard(request, organization_id=None):
    organization = _get_organization_for_user(request.user, organization_id)
    version = CacheService.get_version("agency_dashboard", organization.id)
    cached_context = CacheService.get("agency_dashboard", "org", organization.id, "user", request.user.id, version=version)
    if cached_context is not None:
        return render(request, "agency/dashboard.html", cached_context)

    clients = organization.clients.filter(is_active=True).annotate(
        platform_account_count=Count("platform_accounts", distinct=True),
        competitor_count=Count("competitors", distinct=True),
    )
    platform_accounts = PlatformAccount.objects.filter(agency_client__organization=organization).select_related("platform", "agency_client")
    competitors = Competitor.objects.filter(agency_client__organization=organization).select_related("platform", "platform_account", "agency_client")
    context = {
        "organization": organization,
        "organizations": _agency_organizations(request.user),
        "clients": clients,
        "platform_accounts": platform_accounts[:8],
        "platform_account_count": platform_accounts.count(),
        "competitors": competitors[:8],
        "competitor_count": competitors.count(),
        "can_manage": _user_can_manage(organization, request.user),
        "can_manage_clients": _user_has_permission(organization, request.user, "manage_clients"),
        "can_manage_accounts": _user_has_permission(organization, request.user, "manage_accounts"),
        "can_manage_competitors": _user_has_permission(organization, request.user, "manage_competitors"),
        "can_manage_members": _user_has_permission(organization, request.user, "manage_members"),
        "can_view_reports": _user_has_permission(organization, request.user, "view_reports"),
        "can_access_agency_menu": _user_has_menu_permission(organization, request.user, "agency_dashboard"),
        "client_limit": organization.client_limit,
        "client_count": organization.active_client_count(),
        "seat_limit": organization.seat_limit,
        "member_count": organization.active_member_count(),
    }
    context["organizations"] = list(context["organizations"])
    context["clients"] = list(context["clients"])
    context["platform_accounts"] = list(context["platform_accounts"])
    context["competitors"] = list(context["competitors"])
    CacheService.set(
        "agency_dashboard",
        "org",
        organization.id,
        "user",
        request.user.id,
        value=context,
        timeout=AGENCY_DASHBOARD_CACHE_TIMEOUT,
        version=version,
    )
    return render(request, "agency/dashboard.html", context)


@login_required
def agency_branding(request, organization_id):
    organization = _get_organization_for_user(request.user, organization_id)
    if not (
        _user_has_permission(organization, request.user, "manage_members")
        or _user_has_permission(organization, request.user, "manage_billing")
    ):
        messages.error(request, "Bu ajans markasını düzenleme yetkiniz yok.")
        return redirect("agency_dashboard_org", organization_id=organization.id)

    if request.method == "POST":
        form = OrganizationBrandingForm(request.POST, request.FILES, instance=organization)
        if form.is_valid():
            form.save()
            _invalidate_agency_cache(organization)
            messages.success(request, "Ajans logosu ve rapor marka ayarları güncellendi.")
            return redirect("agency_dashboard_org", organization_id=organization.id)
    else:
        form = OrganizationBrandingForm(instance=organization)

    return render(request, "agency/branding_form.html", {"organization": organization, "form": form})


@login_required
def agency_client_create(request, organization_id):
    organization = _get_organization_for_user(request.user, organization_id)
    if not _user_has_permission(organization, request.user, "manage_clients"):
        messages.error(request, "Müşteri ekleme yetkiniz yok.")
        return redirect("agency_dashboard_org", organization_id=organization.id)
    if not organization.has_available_client_slot():
        messages.error(request, "Ajans paketinizdeki müşteri/marka limiti doldu.")
        return redirect("agency_dashboard_org", organization_id=organization.id)

    if request.method == "POST":
        form = AgencyClientForm(request.POST, request.FILES)
        if form.is_valid():
            client = form.save(commit=False)
            client.organization = organization
            client.save()
            _invalidate_agency_cache(organization)
            messages.success(request, f"{client.name} müşteri alanı oluşturuldu.")
            return redirect("agency_client_detail", organization_id=organization.id, client_id=client.id)
    else:
        form = AgencyClientForm(initial={"is_active": True})

    return render(request, "agency/client_form.html", {"organization": organization, "form": form})


@login_required
def agency_client_detail(request, organization_id, client_id):
    organization = _get_organization_for_user(request.user, organization_id)
    client = get_object_or_404(organization.clients, id=client_id)
    platform_accounts = client.platform_accounts.select_related("platform").order_by("platform__name", "account_name")
    competitors = client.competitors.select_related("platform", "platform_account").order_by("name")
    assignment_form = AgencyAccountAssignmentForm(organization=organization, user=request.user)
    return render(
        request,
        "agency/client_detail.html",
        {
            "organization": organization,
            "client": client,
            "platform_accounts": platform_accounts,
            "competitors": competitors,
            "assignment_form": assignment_form,
            "can_manage": _user_can_manage(organization, request.user),
            "can_manage_accounts": _user_has_permission(organization, request.user, "manage_accounts"),
            "can_manage_competitors": _user_has_permission(organization, request.user, "manage_competitors"),
        },
    )


@login_required
def agency_client_assign_account(request, organization_id, client_id):
    organization = _get_organization_for_user(request.user, organization_id)
    client = get_object_or_404(organization.clients, id=client_id)
    if not _user_has_permission(organization, request.user, "manage_accounts"):
        messages.error(request, "Hesap-müşteri ilişkisi yönetme yetkiniz yok.")
        return redirect("agency_client_detail", organization_id=organization.id, client_id=client.id)

    if request.method == "POST":
        form = AgencyAccountAssignmentForm(request.POST, organization=organization, user=request.user)
        if form.is_valid():
            account = form.cleaned_data["platform_account"]
            account.agency_client = client
            account.save(update_fields=["agency_client", "updated_at"])
            _invalidate_agency_cache(organization)
            messages.success(request, f"{account} hesabı {client.name} müşterisine bağlandı.")
    return redirect("agency_client_detail", organization_id=organization.id, client_id=client.id)


@login_required
def agency_members(request, organization_id):
    organization = _get_organization_for_user(request.user, organization_id)
    if not _user_has_permission(organization, request.user, "manage_members"):
        messages.error(request, "Ekip yönetimi yetkiniz yok.")
        return redirect("agency_dashboard_org", organization_id=organization.id)

    ensure_default_agency_role_groups(organization)
    members = organization.members.select_related("user", "role_group").order_by("role_group__name", "user__email")
    invite_form = OrganizationMemberInviteForm(organization=organization)
    return render(
        request,
        "agency/members.html",
        {
            "organization": organization,
            "members": members,
            "invite_form": invite_form,
            "role_groups": organization.role_groups.order_by("name"),
            "seat_limit": organization.seat_limit,
            "member_count": organization.active_member_count(),
        },
    )


@login_required
def agency_member_invite(request, organization_id):
    organization = _get_organization_for_user(request.user, organization_id)
    if not _user_has_permission(organization, request.user, "manage_members"):
        messages.error(request, "Kullanıcı ekleme yetkiniz yok.")
        return redirect("agency_dashboard_org", organization_id=organization.id)

    if request.method != "POST":
        return redirect("agency_members", organization_id=organization.id)

    ensure_default_agency_role_groups(organization)
    form = OrganizationMemberInviteForm(request.POST, organization=organization)
    if not form.is_valid():
        members = organization.members.select_related("user", "role_group").order_by("role_group__name", "user__email")
        return render(request, "agency/members.html", {
            "organization": organization,
            "members": members,
            "invite_form": form,
            "role_groups": organization.role_groups.order_by("name"),
            "seat_limit": organization.seat_limit,
            "member_count": organization.active_member_count(),
        })

    email = (form.cleaned_data.get("email") or "").strip().lower()
    username_input = form.cleaned_data["username"].strip()
    user = User.objects.filter(email__iexact=email).first() if email else None
    if user is None:
        user = User.objects.filter(username__iexact=username_input).first()
    if user is not None:
        other_membership = (
            user.organization_memberships
            .exclude(organization=organization)
            .select_related("organization")
            .first()
        )
        other_owned_organization = user.owned_organizations.exclude(pk=organization.pk).first()
        if other_membership:
            messages.error(
                request,
                f"Bu kullanıcı zaten {other_membership.organization.name} ajansına bağlıdır. "
                "Bir kullanıcı birden fazla ajansa bağlanamaz.",
            )
            return redirect("agency_members", organization_id=organization.id)
        if other_owned_organization:
            messages.error(
                request,
                f"Bu kullanıcı {other_owned_organization.name} ajansının sahibidir ve başka ajansa bağlanamaz.",
            )
            return redirect("agency_members", organization_id=organization.id)
        if user.id == organization.owner_id:
            messages.error(request, "Ajans sahibi alt kullanıcı olarak eklenemez.")
            return redirect("agency_members", organization_id=organization.id)
    existing_member = organization.members.filter(user=user).first() if user else None
    if not existing_member and not organization.has_available_seat():
        messages.error(request, "Ajans paketinizdeki kullanıcı limiti doldu.")
        return redirect("agency_members", organization_id=organization.id)

    role_group = form.cleaned_data["role_group"]
    legacy_role = role_group.system_key if role_group.system_key in {
        OrganizationMember.ROLE_ADMIN,
        OrganizationMember.ROLE_EDITOR,
        OrganizationMember.ROLE_VIEWER,
    } else OrganizationMember.ROLE_VIEWER

    with transaction.atomic():
        user_was_created = user is None
        if user is None:
            username_base = username_input.replace(".", "_")[:140]
            username = username_base
            suffix = 1
            while User.objects.filter(username__iexact=username).exists():
                suffix += 1
                username = f"{username_base[:135]}_{suffix}"
            user = User.objects.create_user(
                username=username,
                email=email,
                password=form.cleaned_data["password1"],
                first_name=form.cleaned_data["first_name"].strip(),
                last_name=form.cleaned_data["last_name"].strip(),
            )
        from allauth.account.models import EmailAddress

        email_address, _ = EmailAddress.objects.get_or_create(
            user=user,
            email__iexact=email,
            defaults={"email": email, "primary": True, "verified": False},
        )
        if not email_address.verified:
            email_address.send_confirmation(request, signup=user_was_created)

        member, created = OrganizationMember.objects.update_or_create(
            organization=organization,
            user=user,
            defaults={
                "role": legacy_role,
                "role_group": role_group,
                "is_managed_subaccount": bool(
                    user_was_created
                    or (existing_member and existing_member.is_managed_subaccount)
                ),
                "is_active": True,
                "invited_email": email,
            },
        )
    _invalidate_agency_cache(organization)
    member_label = email or user.username
    messages.success(request, f"{member_label} ajans ekibine {'eklendi' if created else 'güncellendi'}.")
    return redirect("agency_members", organization_id=organization.id)


@login_required
def agency_member_update(request, organization_id, member_id):
    organization = _get_organization_for_user(request.user, organization_id)
    member = get_object_or_404(organization.members.select_related("user", "role_group"), id=member_id)
    if not _user_has_permission(organization, request.user, "manage_members"):
        messages.error(request, "Rol düzenleme yetkiniz yok.")
        return redirect("agency_dashboard_org", organization_id=organization.id)
    if member.user_id == organization.owner_id:
        messages.error(request, "Ajans sahibinin rolü buradan değiştirilemez.")
        return redirect("agency_members", organization_id=organization.id)

    if request.method == "POST":
        form = OrganizationMemberRoleForm(request.POST, instance=member, organization=organization)
        if form.is_valid():
            updated_member = form.save(commit=False)
            if updated_member.role_group and updated_member.role_group.system_key in {
                OrganizationMember.ROLE_ADMIN,
                OrganizationMember.ROLE_EDITOR,
                OrganizationMember.ROLE_VIEWER,
            }:
                updated_member.role = updated_member.role_group.system_key
            else:
                updated_member.role = OrganizationMember.ROLE_VIEWER
            updated_member.save()
            _invalidate_agency_cache(organization)
            messages.success(request, f"{member.user.email or member.user.username} rolü güncellendi.")
            return redirect("agency_members", organization_id=organization.id)
    else:
        ensure_default_agency_role_groups(organization)
        form = OrganizationMemberRoleForm(instance=member, organization=organization)

    return render(request, "agency/member_form.html", {"organization": organization, "member": member, "form": form})


@login_required
def agency_subaccount_delete(request, organization_id, member_id):
    organization = _get_organization_for_user(request.user, organization_id)
    if not _user_has_permission(organization, request.user, "manage_members"):
        messages.error(request, "Alt hesap silme yetkiniz yok.")
        return redirect("agency_dashboard_org", organization_id=organization.id)
    if request.method != "POST":
        return redirect("agency_members", organization_id=organization.id)

    member = get_object_or_404(organization.members.select_related("user"), id=member_id)
    if member.user_id in {organization.owner_id, request.user.id}:
        messages.error(request, "Bu alt hesap silinemez.")
        return redirect("agency_members", organization_id=organization.id)

    user = member.user
    member_label = user.email or user.username
    if member.is_managed_subaccount:
        user.delete()
        success_message = f"{member_label} alt hesabı kalıcı olarak silindi."
    else:
        member.delete()
        success_message = f"{member_label} kullanıcısının bu ajanstaki erişimi kaldırıldı."
    _invalidate_agency_cache(organization)
    messages.success(request, success_message)
    return redirect("agency_members", organization_id=organization.id)


@login_required
def agency_role_group_create(request, organization_id):
    organization = _get_organization_for_user(request.user, organization_id)
    if not _user_has_permission(organization, request.user, "manage_members"):
        messages.error(request, "Yetki grubu oluşturma izniniz yok.")
        return redirect("agency_dashboard_org", organization_id=organization.id)

    if request.method == "POST":
        form = AgencyRoleGroupForm(request.POST, organization=organization)
        if form.is_valid():
            group = form.save()
            _invalidate_agency_cache(organization)
            messages.success(request, f"{group.name} yetki grubu oluşturuldu.")
            return redirect("agency_members", organization_id=organization.id)
    else:
        form = AgencyRoleGroupForm(organization=organization, initial={"can_view_reports": True, "is_active": True})
    return render(request, "agency/role_group_form.html", {
        "organization": organization,
        "form": form,
        "role_group": None,
    })


@login_required
def agency_role_group_update(request, organization_id, group_id):
    organization = _get_organization_for_user(request.user, organization_id)
    if not _user_has_permission(organization, request.user, "manage_members"):
        messages.error(request, "Yetki grubu düzenleme izniniz yok.")
        return redirect("agency_dashboard_org", organization_id=organization.id)
    role_group = get_object_or_404(organization.role_groups, id=group_id)

    if request.method == "POST":
        form = AgencyRoleGroupForm(request.POST, instance=role_group, organization=organization)
        if form.is_valid():
            form.save()
            _invalidate_agency_cache(organization)
            messages.success(request, f"{role_group.name} yetki grubu güncellendi.")
            return redirect("agency_members", organization_id=organization.id)
    else:
        form = AgencyRoleGroupForm(instance=role_group, organization=organization)
    return render(request, "agency/role_group_form.html", {
        "organization": organization,
        "form": form,
        "role_group": role_group,
    })


def _connect_agency_platform_account(request, organization, client_id=None):
    posted_client_id = request.POST.get("agency_client") or client_id
    client = get_object_or_404(organization.clients.filter(is_active=True), id=posted_client_id)
    platform_code = (request.POST.get("platform") or "").strip()
    account_name = (request.POST.get("account_name") or "").strip()
    account_id = (request.POST.get("account_id") or "").strip()
    access_token = (request.POST.get("access_token") or "").strip()
    defaults = PLATFORM_DEFAULTS.get(platform_code)
    if not defaults:
        messages.error(request, "Desteklenen bir platform seçin.")
        return redirect(request.path)
    platform, _ = Platform.objects.get_or_create(code=platform_code, defaults={**defaults, "is_active": True})
    try:
        if platform_code == "instagram":
            if not access_token:
                raise ValueError("Instagram access tokenı zorunludur.")
            saved = _save_verified_instagram_accounts(request.user, platform, access_token, agency_client=client)
        elif platform_code in {"facebook", "youtube", "tiktok", "linkedin", "x"}:
            if not access_token:
                raise ValueError(f"{platform.name} access tokenı zorunludur.")
            saved = _save_verified_token_accounts(request.user, platform, access_token, agency_client=client)
        else:
            if not account_id and not account_name:
                raise ValueError("Hesap adı veya platform hesap ID alanlarından en az biri zorunludur.")
            account_id = account_id or account_name
            from core.services.plan_limits import ensure_platform_account_capacity
            ensure_platform_account_capacity(
                request.user, [(platform.code, account_id)], organization=organization
            )
            account, created = PlatformAccount.objects.get_or_create(
                user=request.user, platform=platform, account_id=account_id,
                defaults={"account_name": account_name, "access_token": access_token, "agency_client": client, "is_active": True},
            )
            account.account_name = account_name
            account.access_token = access_token
            account.agency_client = client
            account.is_active = True
            account.save(update_fields=["account_name", "access_token", "agency_client", "is_active", "updated_at"])
            saved = [(account, created)]
            if platform_code == "google_analytics":
                AnalyticsProperty.objects.update_or_create(
                    user=request.user, platform_account=account, property_id=account_id,
                    defaults={"property_name": account_name or f"GA4 Property {account_id}", "property_type": "GA4", "raw_data": {"source": "manual_connection", "account_id": account_id, "account_name": account_name}, "is_active": True},
                )
    except (requests.RequestException, ValueError) as exc:
        messages.error(request, f"{platform.name} hesabı doğrulanamadı: {exc}")
        return redirect(request.path)
    for account, created in saved:
        NotificationHelper.platform_account_connected(user=request.user, account=account, created=created)
    _invalidate_agency_cache(organization)
    names = ", ".join(account.account_name or account.account_id for account, _ in saved)
    messages.success(request, f"{platform.name} hesabı doğrulandı ve {client.name} müşterisine bağlandı: {names}")
    return redirect("agency_client_detail", organization_id=organization.id, client_id=client.id)


@login_required
def agency_platform_account_create(request, organization_id, client_id=None):
    organization = _get_organization_for_user(request.user, organization_id)
    if not _user_has_permission(organization, request.user, "manage_accounts"):
        messages.error(request, "Hesap ekleme yetkiniz yok.")
        return redirect("agency_dashboard_org", organization_id=organization.id)

    selected_client = None
    if client_id:
        selected_client = get_object_or_404(organization.clients, id=client_id)

    if request.method == "POST":
        return _connect_agency_platform_account(request, organization, client_id)
        form = AgencyPlatformAccountForm(request.POST, organization=organization)
        if form.is_valid():
            account = form.save(commit=False)
            account.user = request.user
            account.account_id = account.account_id or account.account_name
            account.save()
            _invalidate_agency_cache(organization)
            messages.success(request, f"{account} müşteri alanına bağlandı.")
            return redirect("agency_client_detail", organization_id=organization.id, client_id=account.agency_client_id)
    else:
        initial = {"is_active": True}
        if selected_client:
            initial["agency_client"] = selected_client
        form = AgencyPlatformAccountForm(organization=organization, initial=initial)

    return render(request, "agency/platform_account_form.html", {
        "organization": organization, "form": form, "selected_client": selected_client,
        "clients": organization.clients.filter(is_active=True).order_by("name"),
        "platforms": PLATFORM_DEFAULTS,
    })


@login_required
def agency_competitor_create(request, organization_id):
    organization = _get_organization_for_user(request.user, organization_id)
    if not _user_has_permission(organization, request.user, "manage_competitors"):
        messages.error(request, "Rakip ekleme yetkiniz yok.")
        return redirect("agency_dashboard_org", organization_id=organization.id)

    if request.method == "POST":
        form = AgencyCompetitorForm(request.POST, organization=organization)
        if form.is_valid():
            competitor = form.save(commit=False)
            competitor.user = request.user
            if competitor.platform_account and not competitor.platform:
                competitor.platform = competitor.platform_account.platform
            competitor.save()
            _invalidate_agency_cache(organization)
            messages.success(request, f"{competitor.name} rakibi müşteri alanına eklendi.")
            return redirect("agency_client_detail", organization_id=organization.id, client_id=competitor.agency_client_id)
    else:
        form = AgencyCompetitorForm(organization=organization, initial={"is_active": True})

    return render(request, "agency/competitor_form.html", {"organization": organization, "form": form})
