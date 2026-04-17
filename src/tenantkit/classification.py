from __future__ import annotations

import warnings
from functools import lru_cache
from typing import Any

from django.apps import apps
from django.conf import settings

from tenantkit.model_config import (
    MODEL_TYPE_SHARED,
    MODEL_TYPE_TENANT,
    MODEL_TYPE_UNCLASSIFIED,
    ModelRegistry,
)

MODEL_TYPE_BOTH = "both"


def _normalize_app_labels(apps: list[str]) -> set[str]:
    return {app.rsplit(".", 1)[-1] for app in apps}


@lru_cache(maxsize=1)
def get_shared_app_labels() -> set[str]:
    shared_apps: list[str] = getattr(settings, "TENANTKIT_SHARED_APPS", [])
    return _normalize_app_labels(shared_apps)


@lru_cache(maxsize=1)
def get_tenant_app_labels() -> set[str]:
    tenant_apps: list[str] = getattr(settings, "TENANTKIT_TENANT_APPS", [])
    return _normalize_app_labels(tenant_apps)


@lru_cache(maxsize=1)
def get_both_app_labels() -> set[str]:
    both_apps: list[str] = getattr(settings, "TENANTKIT_BOTH_APPS", [])
    legacy_dual_apps: list[str] = getattr(settings, "TENANTKIT_DUAL_APPS", [])

    if legacy_dual_apps:
        warnings.warn(
            "TENANTKIT_DUAL_APPS is deprecated; use TENANTKIT_BOTH_APPS instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    return _normalize_app_labels(both_apps + legacy_dual_apps)


def clear_classification_caches() -> None:
    get_shared_app_labels.cache_clear()
    get_tenant_app_labels.cache_clear()
    get_both_app_labels.cache_clear()


def get_model_scope(model: Any) -> str:
    config = ModelRegistry.get_model_config(model)
    if config:
        return str(config["model_type"])

    app_label = getattr(getattr(model, "_meta", None), "app_label", None)
    if not app_label:
        return MODEL_TYPE_UNCLASSIFIED

    if app_label in get_both_app_labels():
        return MODEL_TYPE_BOTH
    if app_label in get_shared_app_labels():
        return MODEL_TYPE_SHARED
    if app_label in get_tenant_app_labels():
        return MODEL_TYPE_TENANT

    return MODEL_TYPE_UNCLASSIFIED


def get_app_scope(app_label: str) -> str:
    if app_label in get_both_app_labels():
        return MODEL_TYPE_BOTH
    if app_label in get_shared_app_labels():
        return MODEL_TYPE_SHARED
    if app_label in get_tenant_app_labels():
        return MODEL_TYPE_TENANT
    return MODEL_TYPE_UNCLASSIFIED


def is_framework_app(app_label: str) -> bool:
    try:
        config = apps.get_app_config(app_label)
    except LookupError:
        return False

    name = config.name
    return name.startswith("django.") or name.startswith(
        (
            "tenantkit",
            "rest_framework",
            "drf_spectacular",
            "django.contrib.admin",
            "django.contrib.sessions",
        )
    )
