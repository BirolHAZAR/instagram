import re
import ipaddress
from dataclasses import dataclass

from django.core.cache import cache
from django.conf import settings
from django.utils import timezone


RATE_RE = re.compile(r"^\s*(?P<count>\d+)\s*/\s*(?P<period>\d+)?\s*(?P<unit>[smhd])\s*$", re.I)
UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 60 * 60 * 24,
}


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    key: str


def parse_rate(rate):
    match = RATE_RE.match(str(rate or ""))
    if not match:
        raise ValueError(f"Invalid rate limit value: {rate}")
    limit = int(match.group("count"))
    period_multiplier = int(match.group("period") or 1)
    seconds = period_multiplier * UNIT_SECONDS[match.group("unit").lower()]
    return limit, seconds


def get_client_ip(request):
    remote_addr = request.META.get("REMOTE_ADDR", "") or "unknown"
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    trusted = getattr(settings, "RATE_LIMIT_TRUSTED_PROXIES", [])
    if forwarded and _ip_in_networks(remote_addr, trusted):
        return forwarded.split(",")[0].strip() or remote_addr
    return remote_addr


def _ip_in_networks(value, networks):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    for network in networks:
        try:
            if address in ipaddress.ip_network(str(network), strict=False):
                return True
        except ValueError:
            continue
    return False


def identity_for_request(request, scope="ip"):
    user = getattr(request, "user", None)
    if scope == "user" and user and user.is_authenticated:
        return f"user:{user.pk}"
    if scope == "user_or_ip" and user and user.is_authenticated:
        return f"user:{user.pk}"
    return f"ip:{get_client_ip(request)}"


def check_rate_limit(*, namespace, identity, rate):
    limit, window_seconds = parse_rate(rate)
    now = int(timezone.now().timestamp())
    window = now // window_seconds
    key = f"rl:{namespace}:{identity}:{window_seconds}:{window}"

    added = cache.add(key, 1, timeout=window_seconds + 5)
    if added:
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=window_seconds + 5)
            count = 1

    remaining = max(0, limit - count)
    retry_after = max(1, ((window + 1) * window_seconds) - now)
    return RateLimitResult(
        allowed=count <= limit,
        limit=limit,
        remaining=remaining,
        retry_after=retry_after if count > limit else 0,
        key=key,
    )
