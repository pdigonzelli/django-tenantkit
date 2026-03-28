from __future__ import annotations

import json
from typing import Any, cast

from tenantkit.models import Tenant
from tenantkit.serializers import TenantReadSerializer, TenantWriteSerializer


class TenantAPIError(ValueError):
    pass


def _require_keys(payload: dict[str, Any], keys: list[str]) -> None:
    missing = [key for key in keys if not payload.get(key)]
    if missing:
        raise TenantAPIError(f"Missing required fields: {', '.join(missing)}")


def _ensure_only_fields(payload: dict[str, Any], allowed: set[str]) -> None:
    extra = sorted(set(payload.keys()) - allowed)
    if extra:
        raise TenantAPIError(f"Unexpected fields: {', '.join(extra)}")


def parse_json_body(raw_body: bytes) -> dict[str, Any]:
    if not raw_body:
        return {}
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise TenantAPIError("Invalid JSON body") from exc
    if not isinstance(data, dict):
        raise TenantAPIError("JSON body must be an object")
    return data


def serialize_tenant(tenant: Tenant) -> dict[str, Any]:
    return cast(dict[str, Any], TenantReadSerializer(tenant).data)


def create_tenant_from_payload(payload: dict[str, Any]) -> Tenant:
    serializer = TenantWriteSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    return cast(Tenant, serializer.save())
