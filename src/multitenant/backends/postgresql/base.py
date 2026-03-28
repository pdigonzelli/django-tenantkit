from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from django.db import connection


def _build_database_wrapper():
    try:  # pragma: no cover - optional dependency
        from django.db.backends.postgresql.base import DatabaseWrapper as Base
    except Exception:  # pragma: no cover - import-safe fallback when psycopg is absent
        Base = object  # type: ignore[assignment]

    class DatabaseWrapper(Base):  # type: ignore[misc,valid-type]
        """PostgreSQL backend with schema switching support."""

        schema_name: str | None = None

        def set_schema(self, schema_name: str | None) -> None:
            self.schema_name = schema_name

        def set_schema_to_public(self) -> None:
            self.schema_name = None

        def _cursor(self, name: str | None = None):
            try:
                cursor = super()._cursor(name=name)
            except AttributeError as exc:  # pragma: no cover - import-safe fallback
                raise ImproperlyConfigured(
                    "PostgreSQL support requires psycopg or psycopg2 to be installed."
                ) from exc

            if self.schema_name:
                cursor.execute(f'SET search_path TO "{self.schema_name}", public')
            return cursor

    return DatabaseWrapper


DatabaseWrapper = _build_database_wrapper()


def activate_schema(schema_name: str | None) -> None:
    """Best-effort schema activation for the current default connection."""

    backend = connection
    set_schema = getattr(backend, "set_schema", None)
    if callable(set_schema):
        set_schema(schema_name)


def deactivate_schema() -> None:
    """Best-effort schema reset for the current default connection."""

    backend = connection
    reset = getattr(backend, "set_schema_to_public", None)
    if callable(reset):
        reset()
