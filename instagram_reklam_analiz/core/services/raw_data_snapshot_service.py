# core/services/raw_data_snapshot_service.py
import hashlib
import json

from django.utils import timezone

from core.models import RawDataSnapshot


def _json_checksum(payload):
    try:
        raw = json.dumps(payload or {}, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        raw = str(payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def save_raw_snapshot(
    *,
    user=None,
    platform=None,
    platform_account=None,
    platform_connection=None,
    sync_job=None,
    campaign=None,
    ad_group=None,
    ad=None,
    creative=None,
    competitor=None,
    source_type="OTHER",
    status="SUCCESS",
    external_id=None,
    external_parent_id=None,
    request_url=None,
    request_params=None,
    response_status_code=None,
    payload=None,
    error_message=None,
    fetched_at=None,
):
    payload = payload or {}
    checksum = _json_checksum(payload)

    return RawDataSnapshot.objects.create(
        user=user,
        platform=platform,
        platform_account=platform_account,
        platform_connection=platform_connection,
        sync_job=sync_job,
        campaign=campaign,
        ad_group=ad_group,
        ad=ad,
        creative=creative,
        competitor=competitor,
        source_type=source_type or "OTHER",
        status=status or "SUCCESS",
        external_id=external_id,
        external_parent_id=external_parent_id,
        request_url=request_url,
        request_params=request_params or {},
        response_status_code=response_status_code,
        payload=payload,
        error_message=error_message,
        checksum=checksum,
        fetched_at=fetched_at or timezone.now(),
    )


def save_raw_error_snapshot(
    *,
    user=None,
    platform=None,
    platform_account=None,
    platform_connection=None,
    sync_job=None,
    source_type="ERROR",
    external_id=None,
    request_url=None,
    request_params=None,
    response_status_code=None,
    payload=None,
    error_message=None,
):
    return save_raw_snapshot(
        user=user,
        platform=platform,
        platform_account=platform_account,
        platform_connection=platform_connection,
        sync_job=sync_job,
        source_type=source_type,
        status="FAILED",
        external_id=external_id,
        request_url=request_url,
        request_params=request_params,
        response_status_code=response_status_code,
        payload=payload or {},
        error_message=error_message,
    )
