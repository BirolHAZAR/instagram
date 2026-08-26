from dataclasses import dataclass

from django.db.models import Q

from core.models import AgencyClient, Organization, PlatformAccount


AGENCY_CLIENT_QUERY_PARAM = "agency_client"
AGENCY_CLIENT_SESSION_KEY = "active_agency_client_id"


@dataclass(frozen=True)
class AgencyScope:
    is_agency: bool
    organization_ids: tuple[int, ...]
    clients: tuple[AgencyClient, ...]
    selected_client: AgencyClient | None

    @property
    def cache_key(self):
        return str(self.selected_client.id) if self.selected_client else "all"


def _organizations_for_user(user):
    if not user or not user.is_authenticated:
        return Organization.objects.none()
    return Organization.objects.filter(
        Q(owner=user) | Q(members__user=user, members__is_active=True),
        is_active=True,
    ).distinct()


def get_agency_scope(request):
    cached = getattr(request, "_agency_scope", None)
    if cached is not None:
        return cached

    user = getattr(request, "user", None)
    organization_ids = tuple(_organizations_for_user(user).values_list("id", flat=True))
    clients = tuple(
        AgencyClient.objects.filter(organization_id__in=organization_ids, is_active=True)
        .select_related("organization")
        .order_by("organization__name", "name")
    )

    selected_id = request.session.get(AGENCY_CLIENT_SESSION_KEY) if organization_ids else None
    if AGENCY_CLIENT_QUERY_PARAM in request.GET:
        raw_value = (request.GET.get(AGENCY_CLIENT_QUERY_PARAM) or "").strip()
        selected_id = int(raw_value) if raw_value.isdigit() else None
        if selected_id:
            request.session[AGENCY_CLIENT_SESSION_KEY] = selected_id
        else:
            request.session.pop(AGENCY_CLIENT_SESSION_KEY, None)

    selected_client = next((client for client in clients if client.id == selected_id), None)
    if selected_id and selected_client is None:
        request.session.pop(AGENCY_CLIENT_SESSION_KEY, None)

    scope = AgencyScope(
        is_agency=bool(organization_ids),
        organization_ids=organization_ids,
        clients=clients,
        selected_client=selected_client,
    )
    request._agency_scope = scope
    return scope


def platform_accounts_for_request(request, queryset=None, *, active_only=False):
    scope = get_agency_scope(request)
    qs = queryset if queryset is not None else PlatformAccount.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    if scope.selected_client:
        return qs.filter(agency_client=scope.selected_client)
    if scope.is_agency:
        return qs.filter(
            Q(user=request.user) | Q(agency_client__organization_id__in=scope.organization_ids)
        ).distinct()
    return qs.filter(user=request.user)


def scope_queryset(request, queryset, *, account_lookup="platform_account", user_lookup="user"):
    """Scope campaign/ad-like querysets without widening non-agency access."""
    scope = get_agency_scope(request)
    if scope.selected_client:
        return queryset.filter(**{f"{account_lookup}__agency_client": scope.selected_client})
    if scope.is_agency:
        return queryset.filter(
            Q(**{user_lookup: request.user})
            | Q(**{f"{account_lookup}__agency_client__organization_id__in": scope.organization_ids})
        ).distinct()
    return queryset.filter(**{user_lookup: request.user})


def scope_client_queryset(request, queryset, *, client_lookup="agency_client", user_lookup="user"):
    scope = get_agency_scope(request)
    if scope.selected_client:
        return queryset.filter(**{client_lookup: scope.selected_client})
    if scope.is_agency:
        return queryset.filter(
            Q(**{user_lookup: request.user})
            | Q(**{f"{client_lookup}__organization_id__in": scope.organization_ids})
        ).distinct()
    return queryset.filter(**{user_lookup: request.user})

