from __future__ import annotations

from typing import Any

from rest_framework import serializers

from tenantkit.models import Tenant


class TenantReadSerializer(serializers.ModelSerializer):
    connection_string = serializers.SerializerMethodField()
    has_connection_string = serializers.SerializerMethodField()
    provisioning_connection_string = serializers.SerializerMethodField()
    has_provisioning_connection_string = serializers.SerializerMethodField()
    deleted = serializers.BooleanField(read_only=True)

    class Meta:
        model = Tenant
        fields = [
            "slug",
            "name",
            "isolation_mode",
            "provisioning_mode",
            "schema_name",
            "connection_alias",
            "connection_string",
            "has_connection_string",
            "provisioning_connection_string",
            "has_provisioning_connection_string",
            "metadata",
            "is_active",
            "deleted",
            "created_at",
            "updated_at",
            "deleted_at",
        ]

    def get_connection_string(self, obj: Tenant) -> None:
        return None

    def get_has_connection_string(self, obj: Tenant) -> bool:
        return bool(obj.connection_string)

    def get_provisioning_connection_string(self, obj: Tenant) -> None:
        return None

    def get_has_provisioning_connection_string(self, obj: Tenant) -> bool:
        return bool(getattr(obj, "provisioning_connection_string", None))


class TenantWriteSerializer(serializers.Serializer):
    slug = serializers.SlugField()
    name = serializers.CharField(max_length=150)
    isolation_mode = serializers.ChoiceField(choices=Tenant.IsolationMode.choices)
    provisioning_mode = serializers.ChoiceField(
        choices=Tenant.ProvisioningMode.choices,
        default=Tenant.ProvisioningMode.AUTO,
        required=False,
    )
    schema_name = serializers.CharField(
        max_length=63, required=False, allow_blank=False, allow_null=False
    )
    connection_alias = serializers.CharField(
        max_length=100, required=False, allow_blank=False, allow_null=False
    )
    connection_string = serializers.CharField(required=False, allow_blank=False)
    provisioning_connection_string = serializers.CharField(
        required=False, allow_blank=False
    )
    metadata = serializers.JSONField(required=False, default=dict)

    def validate_metadata(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("metadata must be an object")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        tenant = Tenant(
            slug=attrs["slug"],
            name=attrs["name"],
            isolation_mode=attrs["isolation_mode"],
            provisioning_mode=attrs.get(
                "provisioning_mode", Tenant.ProvisioningMode.AUTO
            ),
            metadata=attrs.get("metadata", {}),
        )

        if "schema_name" in attrs:
            tenant.schema_name = attrs["schema_name"]
        if "connection_alias" in attrs:
            tenant.connection_alias = attrs["connection_alias"]
        if "connection_string" in attrs:
            tenant.set_connection_string(str(attrs["connection_string"]))
        if "provisioning_connection_string" in attrs:
            tenant.set_provisioning_connection_string(
                str(attrs["provisioning_connection_string"])
            )

        tenant.full_clean()
        attrs["tenant_instance"] = tenant
        return attrs

    def create(self, validated_data: dict[str, Any]) -> Tenant:
        tenant = validated_data.pop("tenant_instance")
        tenant.save()
        return tenant
