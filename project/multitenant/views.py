from __future__ import annotations

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from multitenant.errors import MultitenantError
from multitenant.provisioning import (
    provision_and_migrate_tenant,
    provision_tenant,
    migrate_tenant,
)
from multitenant.models import Tenant
from multitenant.serializers import TenantReadSerializer, TenantWriteSerializer


@extend_schema(
    tags=["Tenants"],
    summary="List all tenants",
    description="Retrieve a list of all tenants ordered by name.",
    responses={
        200: TenantReadSerializer(many=True),
    },
)
class TenantCollectionAPIView(generics.GenericAPIView):
    queryset = Tenant.objects.all().order_by("name")

    @extend_schema(
        operation_id="list_tenants",
        summary="List all tenants",
        responses={200: TenantReadSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        tenants = TenantReadSerializer(self.get_queryset(), many=True)
        return Response({"results": tenants.data})

    @extend_schema(
        operation_id="create_tenant",
        summary="Create a new tenant",
        request=TenantWriteSerializer,
        responses={
            201: TenantReadSerializer,
            400: {"description": "Invalid input data"},
        },
        examples=[
            OpenApiExample(
                "Database Tenant (Manual)",
                value={
                    "slug": "acme-corp",
                    "name": "Acme Corporation",
                    "isolation_mode": "database",
                    "provisioning_mode": "manual",
                    "connection_alias": "tenant_acme_corp",
                    "connection_string": "postgresql://user:pass@localhost:5432/acme_db",
                    "provisioning_connection_string": "postgresql://admin:adminpass@localhost:5432/postgres",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Schema Tenant (Auto)",
                value={
                    "slug": "acme-schema",
                    "name": "Acme Schema Tenant",
                    "isolation_mode": "schema",
                    "provisioning_mode": "auto",
                },
                request_only=True,
            ),
        ],
    )
    def post(self, request, *args, **kwargs):
        serializer = TenantWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = serializer.save()
        return Response(
            TenantReadSerializer(tenant).data, status=status.HTTP_201_CREATED
        )


@extend_schema(
    tags=["Tenants"],
    summary="Tenant detail operations",
    parameters=[
        OpenApiParameter(
            name="slug",
            type=str,
            location=OpenApiParameter.PATH,
            description="Unique tenant identifier (slug)",
        ),
    ],
)
class TenantDetailAPIView(generics.GenericAPIView):
    queryset = Tenant.objects.all()

    def get_object(self):
        return Tenant.objects.filter(slug=self.kwargs["slug"]).first()

    @extend_schema(
        operation_id="get_tenant",
        summary="Get tenant details",
        responses={
            200: TenantReadSerializer,
            404: {"description": "Tenant not found"},
        },
    )
    def get(self, request, slug: str, *args, **kwargs):
        tenant = self.get_object()
        if tenant is None:
            return Response(
                {"error": "Tenant not found"}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(TenantReadSerializer(tenant).data)

    @extend_schema(
        operation_id="delete_tenant",
        summary="Delete a tenant (soft delete)",
        responses={
            200: TenantReadSerializer,
            404: {"description": "Tenant not found"},
        },
    )
    def delete(self, request, slug: str, *args, **kwargs):
        tenant = self.get_object()
        if tenant is None:
            return Response(
                {"error": "Tenant not found"}, status=status.HTTP_404_NOT_FOUND
            )
        tenant.soft_delete()
        tenant.refresh_from_db()
        return Response(TenantReadSerializer(tenant).data)


@extend_schema(
    tags=["Operations"],
    summary="Execute tenant provisioning operations",
    parameters=[
        OpenApiParameter(
            name="slug",
            type=str,
            location=OpenApiParameter.PATH,
            description="Unique tenant identifier (slug)",
        ),
    ],
    request={
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["provision_migrate", "provision_only", "migrate_only"],
                "description": "Provisioning operation to execute",
            }
        },
        "required": ["operation"],
    },
    responses={
        200: {
            "type": "object",
            "properties": {
                "operation": {"type": "string"},
                "result": {"type": "boolean"},
                "tenant": {"type": "object"},
            },
        },
        404: {"description": "Tenant not found"},
        400: {"description": "Invalid operation"},
    },
    examples=[
        OpenApiExample(
            "Provision and Migrate",
            value={"operation": "provision_migrate"},
            request_only=True,
        ),
        OpenApiExample(
            "Provision Only",
            value={"operation": "provision_only"},
            request_only=True,
        ),
        OpenApiExample(
            "Migrate Only",
            value={"operation": "migrate_only"},
            request_only=True,
        ),
    ],
)
class TenantOperationAPIView(APIView):
    def post(self, request, slug: str, *args, **kwargs):
        tenant = Tenant.objects.filter(slug=slug).first()
        if tenant is None:
            return Response(
                {
                    "error": {
                        "code": "TENANT_NOT_FOUND",
                        "message": "Tenant not found.",
                    }
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        operation = str(request.data.get("operation", "")).strip()

        try:
            result = self.execute_operation(tenant, operation)
        except MultitenantError as exc:
            return Response(
                {"error": {"code": exc.code, "message": exc.message}},
                status=exc.status_code,
            )

        return Response(
            {
                "operation": operation,
                "result": result,
                "tenant": TenantReadSerializer(tenant).data,
            }
        )

    def execute_operation(self, tenant: Tenant, operation: str) -> bool:
        if operation == "provision_migrate":
            return provision_and_migrate_tenant(tenant)
        if operation == "provision_only":
            return provision_tenant(tenant)
        if operation == "migrate_only":
            return migrate_tenant(tenant)
        raise MultitenantError(
            f"Unknown operation: {operation}", code="UNKNOWN_OPERATION", status_code=400
        )


tenants_collection = TenantCollectionAPIView.as_view()
tenant_detail = TenantDetailAPIView.as_view()
tenant_operation = TenantOperationAPIView.as_view()
