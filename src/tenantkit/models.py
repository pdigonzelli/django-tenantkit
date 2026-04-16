import logging
import uuid
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify

from .connections import build_connection_alias, build_connection_url, build_schema_name
from .crypto import decrypt_text, encrypt_text
from .managers import AllObjectsManager, AuditManager, TenantSharedManager
from .model_config import shared_model

logger = logging.getLogger(__name__)


class TimestampModel(models.Model):
    """Base abstract model with timestamps and soft-delete support (no user tracking)."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = AuditManager()
    all_objects = AllObjectsManager()

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        abstract = True

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self, *, commit: bool = True, **kwargs: Any) -> None:
        """Soft delete without user tracking. Accepts **kwargs for backward compatibility."""
        self.deleted_at = timezone.now()

        if commit:
            self.save(update_fields=["deleted_at", "updated_at"])

    def restore(self, *, commit: bool = True, **kwargs: Any) -> None:
        """Restore without user tracking. Accepts **kwargs for backward compatibility."""
        self.deleted_at = None

        if commit:
            self.save(update_fields=["deleted_at", "updated_at"])


class AuditModel(TimestampModel):
    """Abstract model with timestamps, soft-delete, and user tracking."""

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="%(class)s_created",
        null=True,
        blank=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="%(class)s_updated",
        null=True,
        blank=True,
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="%(class)s_deleted",
        null=True,
        blank=True,
    )

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        abstract = True

    def soft_delete(self, *, user=None, commit: bool = True, **kwargs: Any) -> None:
        """Soft delete with user tracking."""
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.updated_by = user

        if commit:
            self.save(
                update_fields=["deleted_at", "deleted_by", "updated_at", "updated_by"]
            )

    def restore(self, *, user=None, commit: bool = True, **kwargs: Any) -> None:
        """Restore with user tracking."""
        self.deleted_at = None
        self.deleted_by = user
        self.updated_by = user

        if commit:
            self.save(
                update_fields=["deleted_at", "deleted_by", "updated_at", "updated_by"]
            )


class TenantSharedModel(models.Model):
    allowed_tenants = models.ManyToManyField(
        "Tenant",
        blank=True,
        related_name="%(app_label)s_%(class)s_allowed_tenants",
        help_text="Empty means shared by all tenants; otherwise only listed tenants can access it.",
    )

    objects = TenantSharedManager()
    all_objects = models.Manager()  # noqa: DJ012

    class Meta:
        abstract = True


@shared_model
class Tenant(TimestampModel):
    class IsolationMode(models.TextChoices):
        SCHEMA = "schema"
        DATABASE = "database"

    class ProvisioningMode(models.TextChoices):
        AUTO = "auto"
        MANUAL = "manual"

    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=150)
    isolation_mode = models.CharField(
        max_length=20,
        choices=IsolationMode.choices,
        db_index=True,
    )
    provisioning_mode = models.CharField(
        max_length=20,
        choices=ProvisioningMode.choices,
        default=ProvisioningMode.AUTO,
        db_index=True,
    )
    schema_name = models.CharField(
        max_length=63,
        blank=True,
        null=True,
        unique=True,
        help_text="Required when isolation_mode='schema'.",
    )
    connection_alias = models.CharField(  # noqa: DJ001
        max_length=100,
        blank=True,
        null=True,
        help_text="Required when isolation_mode='database'.",
    )
    connection_string = models.TextField(  # noqa: DJ001
        blank=True,
        null=True,
        help_text="Encrypted connection URL for database tenants.",
    )
    provisioning_connection_string = models.TextField(  # noqa: DJ001
        blank=True,
        null=True,
        help_text="Encrypted admin connection URL used to provision tenant databases.",
    )
    metadata = models.JSONField(default=dict, blank=True)

    is_active = models.BooleanField(default=True, db_index=True)  # type: ignore[call-arg]

    def __str__(self) -> str:
        return str(self.name)

    def save(self, *args: Any, **kwargs: Any):
        if not getattr(self, "_skip_isolation_fields", False):
            self.ensure_isolation_fields()
        result = super().save(*args, **kwargs)

        # Skip auto-provisioning if explicitly requested (e.g., when updating connection strings manually)
        if (
            not getattr(self, "_skip_auto_provisioning", False)
            and self.isolation_mode == self.IsolationMode.DATABASE
        ):
            from .bootstrap import unregister_database_tenant_connection
            from .provisioning import ensure_database_tenant_ready

            if (
                self.is_active
                and not self.deleted
                and self.get_provisioning_connection_string()
            ):
                transaction.on_commit(lambda: ensure_database_tenant_ready(self))
            else:
                transaction.on_commit(
                    lambda: unregister_database_tenant_connection(
                        str(self.connection_alias) if self.connection_alias else None
                    )
                )

        return result

    def _normalized_slug(self) -> str:
        return slugify(self.slug).replace("-", "_")

    def ensure_isolation_fields(self) -> None:
        mode = self.provisioning_mode

        if self.isolation_mode == self.IsolationMode.SCHEMA:
            if mode == self.ProvisioningMode.AUTO:
                if self.schema_name or self.connection_alias or self.connection_string:
                    raise ValidationError(
                        {
                            "schema_name": "Auto provisioning must not receive structural database fields.",
                            "connection_alias": "Auto provisioning must not receive structural database fields.",
                            "connection_string": "Auto provisioning must not receive structural database fields.",
                            "provisioning_connection_string": "Auto provisioning must not receive structural database fields.",
                        }
                    )
                # Validar: auto solo soportado para SQLite
                from .connections import get_default_db_engine

                if get_default_db_engine() not in {"sqlite", "sqlite3"}:
                    raise ValidationError(
                        {
                            "provisioning_mode": "Auto provisioning is only supported for SQLite. Use manual mode for PostgreSQL, MySQL, MariaDB, Oracle, and other server-based databases."
                        }
                    )
                self.schema_name = build_schema_name(str(self.slug))
                self.connection_alias = None
                self.connection_string = None
            else:
                if not self.schema_name:
                    raise ValidationError(
                        {
                            "schema_name": "This field is required for manual schema tenants."
                        }
                    )
                if (
                    self.connection_alias
                    or self.connection_string
                    or self.provisioning_connection_string
                ):
                    raise ValidationError(
                        {
                            "connection_alias": "Manual schema tenants must not define a connection alias.",
                            "connection_string": "Manual schema tenants must not define a connection string.",
                            "provisioning_connection_string": "Manual schema tenants must not define a provisioning connection string.",
                        }
                    )

        if self.isolation_mode == self.IsolationMode.DATABASE:
            if mode == self.ProvisioningMode.AUTO:
                if self.schema_name or self.connection_alias or self.connection_string:
                    raise ValidationError(
                        {
                            "schema_name": "Auto provisioning must not receive structural database fields.",
                            "connection_alias": "Auto provisioning must not receive structural database fields.",
                            "connection_string": "Auto provisioning must not receive structural database fields.",
                        }
                    )
                self.schema_name = None
                self.connection_alias = build_connection_alias(str(self.slug))
                self.connection_string = encrypt_text(
                    build_connection_url(str(self.connection_alias))
                )
            else:
                if self.schema_name:
                    raise ValidationError(
                        {
                            "schema_name": "Manual database tenants must not define a schema name."
                        }
                    )
                if not self.connection_alias:
                    raise ValidationError(
                        {
                            "connection_alias": "This field is required for manual database tenants."
                        }
                    )
                if not self.connection_string:
                    raise ValidationError(
                        {
                            "connection_string": "This field is required for manual database tenants."
                        }
                    )

    def clean(self) -> None:
        super().clean()

        if self.provisioning_mode not in self.ProvisioningMode.values:
            raise ValidationError({"provisioning_mode": "Invalid provisioning mode."})

        # Validate unique connection_alias among active tenants (soft-delete aware)
        if self.connection_alias and self.is_active:
            queryset = Tenant.objects.filter(
                connection_alias=self.connection_alias, is_active=True
            )
            if self.pk:
                queryset = queryset.exclude(pk=self.pk)
            if queryset.exists():
                raise ValidationError(
                    {
                        "connection_alias": "This connection alias is already in use by another active tenant."
                    }
                )

    def set_connection_string(self, plain_text: str) -> None:
        self.connection_string = encrypt_text(plain_text)

    def get_connection_string(self) -> str | None:
        encrypted = getattr(self, "connection_string", None)
        if not encrypted:
            return None
        return decrypt_text(str(encrypted))

    def set_provisioning_connection_string(self, plain_text: str) -> None:
        self.provisioning_connection_string = encrypt_text(plain_text)

    def get_provisioning_connection_string(self) -> str | None:
        encrypted = getattr(self, "provisioning_connection_string", None)
        if not encrypted:
            return None
        return decrypt_text(str(encrypted))

    def soft_delete(
        self, *, commit: bool = True, delete_database: bool = False, **kwargs: Any
    ) -> None:
        """Soft delete tenant. If delete_database=True, also drops physical database and user."""
        # Delete database resources if requested (only for database tenants)
        if delete_database and self.isolation_mode == self.IsolationMode.DATABASE:
            self.delete_database_resources()

        super().soft_delete(commit=False)
        self.is_active = False

        if commit:
            self._skip_isolation_fields = True
            try:
                self.save(
                    update_fields=[
                        "deleted_at",
                        "is_active",
                        "updated_at",
                    ]
                )
            finally:
                self._skip_isolation_fields = False

    def delete_database_resources(self) -> bool:
        """Delete physical database and user. Returns True if successful."""
        if self.isolation_mode != self.IsolationMode.DATABASE:
            return False

        connection_string = self.get_connection_string()
        provisioning_connection_string = self.get_provisioning_connection_string()

        if not connection_string:
            return False

        try:
            from .provisioning import delete_database_and_user

            return delete_database_and_user(
                connection_string, provisioning_connection_string
            )
        except Exception as exc:
            logger.error("Failed to delete database resources: %s", exc)
            return False

    def restore(self, *, commit: bool = True, **kwargs: Any) -> None:
        super().restore(commit=False)
        self.is_active = True

        if commit:
            self._skip_isolation_fields = True
            try:
                self.save(
                    update_fields=[
                        "deleted_at",
                        "is_active",
                        "updated_at",
                    ]
                )
            finally:
                self._skip_isolation_fields = False


@shared_model
class TenantInvitation(TimestampModel):
    class Status(models.TextChoices):
        PENDING = "pending"
        ACCEPTED = "accepted"
        REVOKED = "revoked"
        EXPIRED = "expired"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField()
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Identifier of the user who accepted (stored as string for cross-DB compatibility).",
    )

    class Meta(TimestampModel.Meta):  # type: ignore[misc]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "email"],
                name="unique_tenant_invitation_email",
            )
        ]

    def __str__(self) -> str:
        return f"{self.email} → {self.tenant}"

    @property
    def expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= timezone.now())

    def mark_accepted(self, *, user: str | None = None, commit: bool = True) -> None:
        self.status = self.Status.ACCEPTED
        self.accepted_at = timezone.now()
        self.accepted_by = user or ""

        if commit:
            self.save(
                update_fields=[
                    "status",
                    "accepted_at",
                    "accepted_by",
                    "updated_at",
                ]
            )

    def revoke(self, *, commit: bool = True, **kwargs: Any) -> None:
        self.status = self.Status.REVOKED

        if commit:
            self.save(update_fields=["status", "updated_at"])


@shared_model
class TenantSetting(TimestampModel):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="settings",
    )
    key = models.CharField(max_length=120)
    value = models.JSONField(default=dict, blank=True)

    class Meta(TimestampModel.Meta):  # type: ignore[misc]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "key"],
                name="unique_tenant_setting_key",
            )
        ]

    def __str__(self) -> str:
        return f"{self.tenant}:{self.key}"
