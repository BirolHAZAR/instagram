import time
import hashlib
import re
from typing import Any

from django.core.cache import cache, caches


class CacheService:
    """Small project-level wrapper around Django's configured cache backend."""

    DEFAULT_TIMEOUT = 300
    VERSION_TIMEOUT = 60 * 60 * 24 * 30
    KEY_PREFIX = "reklamanaliz"

    @classmethod
    def make_key(cls, namespace: str, *parts: Any, version: int | None = None) -> str:
        safe_parts = [cls._safe_part(part) for part in parts if part is not None]
        version_part = f"v{version}" if version is not None else "v1"
        return ":".join([cls.KEY_PREFIX, namespace, version_part, *safe_parts])

    @staticmethod
    def _safe_part(part: Any) -> str:
        raw = str(part)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_") or "empty"
        if len(safe) > 80:
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
            safe = f"{safe[:48]}_{digest}"
        return safe

    @classmethod
    def get(cls, namespace: str, *parts: Any, version: int | None = None, default: Any = None) -> Any:
        return cache.get(cls.make_key(namespace, *parts, version=version), default)

    @classmethod
    def set(
        cls,
        namespace: str,
        *parts: Any,
        value: Any,
        timeout: int | None = None,
        version: int | None = None,
    ) -> bool:
        key = cls.make_key(namespace, *parts, version=version)
        cache.set(key, value, timeout if timeout is not None else cls.DEFAULT_TIMEOUT)
        return True

    @classmethod
    def delete(cls, namespace: str, *parts: Any, version: int | None = None) -> bool:
        return cache.delete(cls.make_key(namespace, *parts, version=version))

    @classmethod
    def version_key(cls, namespace: str, *parts: Any) -> str:
        return cls.make_key(f"{namespace}:version", *parts, version=1)

    @classmethod
    def get_version(cls, namespace: str, *parts: Any) -> int:
        key = cls.version_key(namespace, *parts)
        current = cache.get(key)
        if current is None:
            initial = int(time.time() * 1000)
            cache.add(key, initial, cls.VERSION_TIMEOUT)
            current = cache.get(key, initial)
        return int(current)

    @classmethod
    def bump_version(cls, namespace: str, *parts: Any) -> int:
        key = cls.version_key(namespace, *parts)
        initial = int(time.time() * 1000)
        if cache.add(key, initial, cls.VERSION_TIMEOUT):
            return initial
        try:
            return int(cache.incr(key))
        except ValueError:
            cache.set(key, initial, cls.VERSION_TIMEOUT)
            return initial

    @classmethod
    def get_stats(cls) -> dict[str, Any]:
        backend = caches["default"]
        stats = {
            "backend": backend.__class__.__module__,
            "available": True,
        }
        try:
            client = getattr(backend, "_cache", None)
            if hasattr(client, "get_client"):
                redis_client = client.get_client(write=True)
                info = redis_client.info()
                stats.update(
                    {
                        "used_memory": info.get("used_memory_human") or info.get("used_memory"),
                        "total_keys": sum(db.get("keys", 0) for name, db in info.items() if str(name).startswith("db")),
                        "hit_rate": _redis_hit_rate(info),
                    }
                )
        except Exception as exc:
            stats["available"] = False
            stats["error"] = str(exc)
        return stats


class DashboardCacheManager:
    TIMEOUT = 300

    @classmethod
    def get_user_dashboard(cls, user_id: int, scope_key: str = "all") -> Any:
        version = CacheService.get_version("dashboard", user_id)
        return CacheService.get("dashboard", "user", user_id, "scope", scope_key, version=version)

    @classmethod
    def set_user_dashboard(cls, user_id: int, data: Any, timeout: int | None = None, scope_key: str = "all") -> bool:
        version = CacheService.get_version("dashboard", user_id)
        return CacheService.set(
            "dashboard",
            "user", user_id, "scope", scope_key,
            value=data,
            timeout=timeout if timeout is not None else cls.TIMEOUT,
            version=version,
        )

    @classmethod
    def invalidate_user_dashboard(cls, user_id: int) -> int:
        return CacheService.bump_version("dashboard", user_id)


def _redis_hit_rate(info: dict[str, Any]) -> float:
    hits = int(info.get("keyspace_hits") or 0)
    misses = int(info.get("keyspace_misses") or 0)
    total = hits + misses
    if total == 0:
        return 0.0
    return round((hits / total) * 100, 2)
