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
        include_public_schema: bool = True

        def set_schema(
            self, schema_name: str | None, include_public: bool = True
        ) -> None:
            self.schema_name = schema_name
            self.include_public_schema = include_public

        def set_schema_to_public(self) -> None:
            self.schema_name = None
            self.include_public_schema = True

        def _set_search_path(self, cursor) -> None:
            if not self.schema_name:
                return

            if self.include_public_schema:
                cursor.execute(f'SET search_path TO "{self.schema_name}", public')
            else:
                cursor.execute(f'SET search_path TO "{self.schema_name}"')

        def _cursor(self, name: str | None = None):
            try:
                if name is not None and self.schema_name:
                    setup_cursor = super()._cursor(name=None)
                    try:
                        self._set_search_path(setup_cursor)
                    finally:
                        setup_cursor.close()

                cursor = super()._cursor(name=name)
            except AttributeError as exc:  # pragma: no cover - import-safe fallback
                raise ImproperlyConfigured(
                    "PostgreSQL support requires psycopg or psycopg2 to be installed."
                ) from exc

            if name is None:
                self._set_search_path(cursor)
            return cursor

    return DatabaseWrapper


DatabaseWrapper = _build_database_wrapper()


def activate_schema(schema_name: str | None, include_public: bool = True) -> None:
    """Best-effort schema activation for the current default connection."""

    backend = connection
    set_schema = getattr(backend, "set_schema", None)
    if callable(set_schema):
        set_schema(schema_name, include_public=include_public)


def deactivate_schema() -> None:
    """Best-effort schema reset for the current default connection."""

    backend = connection
    reset = getattr(backend, "set_schema_to_public", None)
    if callable(reset):
        reset()
