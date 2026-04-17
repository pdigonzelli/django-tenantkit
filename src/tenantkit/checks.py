from __future__ import annotations

from django.apps import apps
from django.core.checks import Warning, register

from tenantkit.classification import get_app_scope, get_model_scope, is_framework_app
from tenantkit.model_config import MODEL_TYPE_UNCLASSIFIED


@register()
def check_unclassified_models(app_configs, **kwargs):
    issues = []

    for model in apps.get_models():
        app_label = model._meta.app_label

        if is_framework_app(app_label):
            continue

        if get_app_scope(app_label) != MODEL_TYPE_UNCLASSIFIED:
            continue

        if get_model_scope(model) != MODEL_TYPE_UNCLASSIFIED:
            continue

        issues.append(
            Warning(
                f"Model {model.__module__}.{model.__name__} is not classified for tenant routing.",
                hint=(
                    "Classify the model with @shared_model/@tenant_model or configure its app "
                    "in TENANTKIT_SHARED_APPS, TENANTKIT_TENANT_APPS, TENANTKIT_BOTH_APPS, "
                    "or TENANTKIT_MIXED_APPS."
                ),
                id="tenantkit.W001",
            )
        )

    return issues
