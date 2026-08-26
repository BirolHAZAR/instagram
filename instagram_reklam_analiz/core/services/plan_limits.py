from core.models import PlatformAccount
from core.services.agency_permission_matrix import get_user_entitlement_plan


def ensure_platform_account_capacity(user, candidates, organization=None):
    """Enforce one total account pool across every platform, never per platform."""
    plan = get_user_entitlement_plan(user)
    if not plan:
        raise ValueError("Aktif deneme veya abonelik bulunamadı.")
    limit = int(plan.max_instagram_accounts or 0)
    if limit <= 0:
        raise ValueError("Paketiniz platform hesabı bağlantısını içermiyor.")

    scope = PlatformAccount.objects.filter(is_active=True)
    if organization is not None:
        scope = scope.filter(agency_client__organization=organization)
    else:
        scope = scope.filter(user=user, agency_client__isnull=True)
    current = scope.count()
    new_count = 0
    seen = set()
    for platform_code, account_id in candidates:
        key = (str(platform_code), str(account_id))
        if key in seen:
            continue
        seen.add(key)
        existing = scope.filter(platform__code=key[0], account_id=key[1]).exists()
        if not existing:
            new_count += 1
    if current + new_count > limit:
        raise ValueError(
            f"Paketiniz toplam {limit} platform hesabına izin veriyor. "
            f"Mevcut: {current}, eklenmek istenen yeni hesap: {new_count}."
        )
    return True
