from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

from django.core.management import call_command
from django.db import connections

from multitenant.connections import parse_connection_url
from multitenant.backends.postgresql.base import activate_schema, deactivate_schema
from multitenant.errors import SchemaProvisioningUnsupportedError

if TYPE_CHECKING:
    from multitenant.models import Tenant


logger = logging.getLogger(__name__)


class DatabaseProvisioningStrategy(ABC):
    """Abstract base class for database provisioning strategies."""

    @abstractmethod
    def ensure_database_exists(
        self, connection_string: str, provisioning_url: str | None = None
    ) -> bool:
        """Create database if it doesn't exist."""
        pass

    @abstractmethod
    def ensure_user_exists(
        self, username: str, password: str, provisioning_url: str
    ) -> bool:
        """Create user if it doesn't exist."""
        pass

    @abstractmethod
    def grant_permissions(
        self, database_name: str, username: str, provisioning_url: str
    ) -> bool:
        """Grant permissions to user on database."""
        pass

    @abstractmethod
    def delete_database_and_user(
        self, connection_string: str, provisioning_url: str | None = None
    ) -> bool:
        """Delete database and user."""
        pass

    @abstractmethod
    def database_exists(self, connection_string: str, provisioning_url: str) -> bool:
        """Check if database exists."""
        pass

    @abstractmethod
    def user_exists(self, username: str, provisioning_url: str) -> bool:
        """Check if user exists."""
        pass


class SQLiteProvisioningStrategy(DatabaseProvisioningStrategy):
    """Provisioning strategy for SQLite databases."""

    def ensure_database_exists(
        self, connection_string: str, provisioning_url: str | None = None
    ) -> bool:
        """For SQLite, just ensure the directory exists."""
        parsed = parse_connection_url(connection_string)
        database_name = str(parsed.get("NAME") or "").strip()

        if not database_name or database_name == ":memory:":
            return True

        db_dir = os.path.dirname(database_name)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info("tenant.sqlite.dir_created", extra={"directory": db_dir})

        # SQLite creates the file automatically on first connection
        logger.info("tenant.sqlite.ready", extra={"database": database_name})
        return True

    def ensure_user_exists(
        self, username: str, password: str, provisioning_url: str
    ) -> bool:
        """SQLite doesn't have users - no-op."""
        return True

    def grant_permissions(
        self, database_name: str, username: str, provisioning_url: str
    ) -> bool:
        """SQLite doesn't have user permissions - no-op."""
        return True

    def delete_database_and_user(
        self, connection_string: str, provisioning_url: str | None = None
    ) -> bool:
        """Delete SQLite database file."""
        parsed = parse_connection_url(connection_string)
        database_name = str(parsed.get("NAME") or "").strip()

        if not database_name or database_name == ":memory:":
            return True

        try:
            if os.path.exists(database_name):
                os.remove(database_name)
                logger.info("tenant.sqlite.deleted", extra={"database": database_name})
            return True
        except Exception as exc:
            logger.error(
                "tenant.sqlite.delete_failed",
                extra={"database": database_name, "error": str(exc)},
            )
            return False

    def database_exists(self, connection_string: str, provisioning_url: str) -> bool:
        """Check if SQLite file exists."""
        parsed = parse_connection_url(connection_string)
        database_name = str(parsed.get("NAME") or "").strip()

        if not database_name or database_name == ":memory:":
            return True

        return os.path.exists(database_name)

    def user_exists(self, username: str, provisioning_url: str) -> bool:
        """SQLite doesn't have users - always returns True."""
        return True


class PostgreSQLProvisioningStrategy(DatabaseProvisioningStrategy):
    """Provisioning strategy for PostgreSQL databases."""

    def _parse_url(self, url: str) -> PostgresProvisioningTarget | None:
        return _parse_postgres_url(url)

    def _get_connection_string(self, target: PostgresProvisioningTarget) -> str:
        return _get_psycopg_connection_string(target)

    def database_exists(self, connection_string: str, provisioning_url: str) -> bool:
        try:
            import psycopg
        except ImportError:
            logger.warning("psycopg not installed")
            return False

        target = self._parse_url(provisioning_url)
        if target is None:
            return False

        database_name = self._database_name_from_url(connection_string)
        if not database_name:
            return False

        try:
            conn = psycopg.connect(self._get_connection_string(target))
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s", (database_name,)
                )
                result = cur.fetchone()
            conn.close()
            return result is not None
        except Exception as exc:
            logger.error("Failed to check database existence: %s", exc)
            raise RuntimeError(f"Failed to inspect database: {exc}") from exc

    def user_exists(self, username: str, provisioning_url: str) -> bool:
        try:
            import psycopg
        except ImportError:
            logger.warning("psycopg not installed")
            return False

        target = self._parse_url(provisioning_url)
        if target is None or not username:
            return False

        try:
            conn = psycopg.connect(self._get_connection_string(target))
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (username,))
                result = cur.fetchone()
            conn.close()
            return result is not None
        except Exception as exc:
            logger.error("Failed to check user existence: %s", exc)
            raise RuntimeError(f"Failed to inspect user: {exc}") from exc

    def _database_name_from_url(self, url: str) -> str:
        parsed = parse_connection_url(url)
        return str(parsed.get("NAME") or "").strip()

    def _parse_connection_url_for_user(self, url: str) -> tuple[str | None, str | None]:
        parsed = urlparse(url)
        username = unquote(parsed.username) if parsed.username else None
        password = unquote(parsed.password) if parsed.password else None
        return username, password

    def ensure_database_exists(
        self, connection_string: str, provisioning_url: str | None = None
    ) -> bool:
        try:
            import psycopg
            from psycopg import sql
        except ImportError:
            logger.warning("psycopg not installed, skipping database provisioning")
            return False

        if not provisioning_url:
            return False

        target = self._parse_url(provisioning_url)
        if target is None:
            return False

        database_name = self._database_name_from_url(connection_string)
        if not database_name:
            return False

        if self.database_exists(connection_string, provisioning_url):
            logger.info("tenant.db.exists", extra={"database": database_name})
            return False

        try:
            conn = psycopg.connect(self._get_connection_string(target))
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
                )
            conn.close()
            logger.info("tenant.db.created", extra={"database": database_name})
            return True
        except psycopg.errors.DuplicateDatabase:
            logger.info("tenant.db.exists", extra={"database": database_name})
            return False
        except Exception as exc:
            logger.error("Failed to create database: %s", exc)
            raise RuntimeError(
                f"Failed to create database {database_name}: {exc}"
            ) from exc

    def ensure_user_exists(
        self, username: str, password: str, provisioning_url: str
    ) -> bool:
        try:
            import psycopg
            from psycopg import sql
        except ImportError:
            logger.warning("psycopg not installed, skipping user provisioning")
            return False

        target = self._parse_url(provisioning_url)
        if target is None:
            return False

        if not username or not password:
            return False

        if self.user_exists(username, provisioning_url):
            logger.info("tenant.user.exists", extra={"user": username})
            return False

        try:
            conn = psycopg.connect(self._get_connection_string(target))
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("CREATE USER {} WITH PASSWORD {}").format(
                        sql.Identifier(username), sql.Literal(password)
                    )
                )
            conn.close()
            logger.info("tenant.user.created", extra={"user": username})
            return True
        except psycopg.errors.DuplicateObject:
            logger.info("tenant.user.exists", extra={"user": username})
            return False
        except Exception as exc:
            logger.error("Failed to create user: %s", exc)
            raise RuntimeError(f"Failed to create user {username}: {exc}") from exc

    def grant_permissions(
        self, database_name: str, username: str, provisioning_url: str
    ) -> bool:
        try:
            import psycopg
            from psycopg import sql
        except ImportError:
            logger.warning("psycopg not installed, skipping permission grants")
            return False

        target = self._parse_url(provisioning_url)
        if target is None:
            return False

        if not database_name or not username:
            return False

        try:
            target_db_conn_str = (
                f"host={target.host} port={target.port} dbname={database_name}"
            )
            if target.user:
                target_db_conn_str += f" user={target.user}"
            if target.password:
                target_db_conn_str += f" password={target.password}"

            conn = psycopg.connect(target_db_conn_str)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(database_name), sql.Identifier(username)
                    )
                )
                cur.execute(
                    sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
                        sql.Identifier(username)
                    )
                )
                cur.execute(
                    sql.SQL("GRANT ALL ON ALL TABLES IN SCHEMA public TO {}").format(
                        sql.Identifier(username)
                    )
                )
                cur.execute(
                    sql.SQL(
                        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {}"
                    ).format(sql.Identifier(username))
                )
            conn.close()
            logger.info(
                "tenant.permissions.granted",
                extra={"database": database_name, "user": username},
            )
            return True
        except Exception as exc:
            logger.error("Failed to grant permissions: %s", exc)
            raise RuntimeError(f"Failed to grant permissions: {exc}") from exc

    def delete_database_and_user(
        self, connection_string: str, provisioning_url: str | None = None
    ) -> bool:
        try:
            import psycopg
            from psycopg import sql
        except ImportError:
            logger.warning("psycopg not installed, cannot delete database resources")
            return False

        admin_connection_string = provisioning_url or connection_string
        database_name = self._database_name_from_url(connection_string)
        username, _ = self._parse_connection_url_for_user(connection_string)

        if not database_name:
            return False

        target = self._parse_url(admin_connection_string)
        if target is None:
            return False

        success = True

        # Drop database
        try:
            conn = psycopg.connect(self._get_connection_string(target))
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pg_terminate_backend(pg_stat_activity.pid)
                    FROM pg_stat_activity
                    WHERE pg_stat_activity.datname = %s
                    AND pid <> pg_backend_pid()
                    """,
                    (database_name,),
                )
                cur.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(
                        sql.Identifier(database_name)
                    )
                )
            conn.close()
            logger.info("tenant.database.dropped", extra={"database": database_name})
        except Exception as exc:
            logger.error(
                "tenant.delete.database_failed",
                extra={"database": database_name, "error": str(exc)},
            )
            success = False

        # Drop user
        if username and username != target.user:
            try:
                conn = psycopg.connect(self._get_connection_string(target))
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("DROP USER IF EXISTS {}").format(
                            sql.Identifier(username)
                        )
                    )
                conn.close()
                logger.info("tenant.user.dropped", extra={"user": username})
            except Exception as exc:
                logger.error(
                    "tenant.delete.user_failed",
                    extra={"user": username, "error": str(exc)},
                )
                success = False

        return success


class ProvisioningStrategyFactory:
    """Factory to get the appropriate provisioning strategy for a database URL."""

    _strategies = {
        "sqlite": SQLiteProvisioningStrategy,
        "postgresql": PostgreSQLProvisioningStrategy,
        "postgres": PostgreSQLProvisioningStrategy,
    }

    @classmethod
    def get_strategy(cls, connection_string: str) -> DatabaseProvisioningStrategy:
        """Get the appropriate strategy for the given database URL."""
        parsed = urlparse(connection_string)
        scheme = parsed.scheme.lower()

        if scheme in cls._strategies:
            return cls._strategies[scheme]()

        # Default to PostgreSQL for unknown schemes
        logger.warning(
            f"Unknown database scheme '{scheme}', defaulting to PostgreSQL strategy"
        )
        return PostgreSQLProvisioningStrategy()


@dataclass(frozen=True)
class PostgresProvisioningTarget:
    host: str
    port: int
    user: str | None
    password: str | None
    maintenance_db: str


def _parse_postgres_url(url: str) -> PostgresProvisioningTarget | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        return None

    return PostgresProvisioningTarget(
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        user=unquote(parsed.username) if parsed.username else None,
        password=unquote(parsed.password) if parsed.password else None,
        maintenance_db=unquote(parsed.path.lstrip("/")) or "postgres",
    )


def _get_psycopg_connection_string(target: PostgresProvisioningTarget) -> str:
    """Build a psycopg connection string from provisioning target."""
    conn_str = f"host={target.host} port={target.port} dbname={target.maintenance_db}"
    if target.user:
        conn_str += f" user={target.user}"
    if target.password:
        conn_str += f" password={target.password}"
    return conn_str


def _database_name_from_connection_url(url: str) -> str:
    parsed = parse_connection_url(url)
    return str(parsed.get("NAME") or "").strip()


def _parse_connection_url_for_user(url: str) -> tuple[str | None, str | None]:
    """Extract username and password from connection URL."""
    parsed = urlparse(url)
    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    return username, password


def user_exists(username: str, provisioning_connection_string: str) -> bool:
    """Check if PostgreSQL user/role exists."""
    try:
        import psycopg
    except ImportError:  # pragma: no cover
        logger.warning("psycopg not installed, cannot check user existence")
        return False

    target = _parse_postgres_url(provisioning_connection_string)
    if target is None:
        return False

    if not username:
        return False

    try:
        conn = psycopg.connect(_get_psycopg_connection_string(target))
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (username,))
            result = cur.fetchone()
        conn.close()
        return result is not None
    except Exception as exc:
        logger.error("Failed to check user existence: %s", exc)
        raise RuntimeError(f"Failed to inspect user: {exc}") from exc


def ensure_user_exists(
    username: str, password: str, provisioning_connection_string: str
) -> bool:
    """Create PostgreSQL user if it doesn't exist."""
    try:
        import psycopg
        from psycopg import sql
    except ImportError:  # pragma: no cover
        logger.warning("psycopg not installed, skipping user provisioning")
        return False

    target = _parse_postgres_url(provisioning_connection_string)
    if target is None:
        return False

    if not username or not password:
        return False

    if user_exists(username, provisioning_connection_string):
        logger.info("tenant.user.exists", extra={"user": username})
        return False

    try:
        conn = psycopg.connect(_get_psycopg_connection_string(target))
        # Need to be in autocommit mode to create user
        conn.autocommit = True
        with conn.cursor() as cur:
            # Create user with password using safe quoting
            cur.execute(
                sql.SQL("CREATE USER {} WITH PASSWORD {}").format(
                    sql.Identifier(username), sql.Literal(password)
                )
            )
        conn.close()
        logger.info("tenant.user.created", extra={"user": username})
        return True
    except psycopg.errors.DuplicateObject:
        logger.info("tenant.user.exists", extra={"user": username})
        return False
    except Exception as exc:
        logger.error("Failed to create user: %s", exc)
        raise RuntimeError(f"Failed to create user {username}: {exc}") from exc


def grant_database_permissions(
    database_name: str, username: str, provisioning_connection_string: str
) -> bool:
    """Grant minimal permissions to user on database."""
    try:
        import psycopg
        from psycopg import sql
    except ImportError:  # pragma: no cover
        logger.warning("psycopg not installed, skipping permission grants")
        return False

    target = _parse_postgres_url(provisioning_connection_string)
    if target is None:
        return False

    if not database_name or not username:
        return False

    try:
        # Connect to the target database (not maintenance db)
        target_db_conn_str = (
            f"host={target.host} port={target.port} dbname={database_name}"
        )
        if target.user:
            target_db_conn_str += f" user={target.user}"
        if target.password:
            target_db_conn_str += f" password={target.password}"

        conn = psycopg.connect(target_db_conn_str)
        conn.autocommit = True
        with conn.cursor() as cur:
            # Grant connect on database
            cur.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database_name), sql.Identifier(username)
                )
            )
            # Grant usage and create on schema public
            cur.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
                    sql.Identifier(username)
                )
            )
            # Grant all on existing tables
            cur.execute(
                sql.SQL("GRANT ALL ON ALL TABLES IN SCHEMA public TO {}").format(
                    sql.Identifier(username)
                )
            )
            # Set default privileges for future tables
            cur.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {}"
                ).format(sql.Identifier(username))
            )
        conn.close()
        logger.info(
            "tenant.permissions.granted",
            extra={"database": database_name, "user": username},
        )
        return True
    except Exception as exc:
        logger.error("Failed to grant permissions: %s", exc)
        raise RuntimeError(f"Failed to grant permissions: {exc}") from exc


def database_exists(connection_string: str, provisioning_connection_string: str) -> bool:
    """Check if database exists using psycopg."""
    try:
        import psycopg
    except ImportError:  # pragma: no cover
        logger.warning("psycopg not installed, cannot check database existence")
        return False

    target = _parse_postgres_url(provisioning_connection_string)
    if target is None:
        return False

    database_name = _database_name_from_connection_url(connection_string)
    if not database_name:
        return False

    try:
        conn = psycopg.connect(_get_psycopg_connection_string(target))
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (database_name,)
            )
            result = cur.fetchone()
        conn.close()
        return result is not None
    except Exception as exc:
        logger.error("Failed to check database existence: %s", exc)
        raise RuntimeError(f"Failed to inspect database: {exc}") from exc


def ensure_database_exists(
    connection_string: str, provisioning_connection_string: str
) -> bool:
    """Create database if it doesn't exist using psycopg."""
    try:
        import psycopg
        from psycopg import sql
    except ImportError:  # pragma: no cover
        logger.warning("psycopg not installed, skipping database provisioning")
        return False

    target = _parse_postgres_url(provisioning_connection_string)
    if target is None:
        logger.info(
            "tenant.db.provisioning.skipped", extra={"connection_string": connection_string}
        )
        return False

    database_name = _database_name_from_connection_url(connection_string)
    if not database_name:
        return False

    if database_exists(connection_string, provisioning_connection_string):
        logger.info("tenant.db.exists", extra={"database": database_name})
        return False

    try:
        conn = psycopg.connect(_get_psycopg_connection_string(target))
        # Need to be in autocommit mode to create database
        conn.autocommit = True
        with conn.cursor() as cur:
            # Create database using psycopg.sql.Identifier for safe quoting
            cur.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
            )
        conn.close()
        logger.info("tenant.db.created", extra={"database": database_name})
        return True
    except psycopg.errors.DuplicateDatabase:
        logger.info("tenant.db.exists", extra={"database": database_name})
        return False
    except Exception as exc:
        logger.error("Failed to create database: %s", exc)
        raise RuntimeError(f"Failed to create database {database_name}: {exc}") from exc


def ensure_database_tenant_ready(tenant: "Tenant") -> bool:
    """Full provisioning flow: database, user, permissions, and registration."""
    if tenant.isolation_mode != tenant.IsolationMode.DATABASE:
        return False

    alias = str(tenant.connection_alias or "")
    connection_string = tenant.get_connection_string()
    if not alias or not connection_string:
        return False

    database_config = parse_connection_url(connection_string)
    database_name = str(database_config.get("NAME") or "").strip()
    if not database_name:
        return False

    provisioning_connection_string = (
        tenant.get_provisioning_connection_string() or connection_string
    )

    # Get the appropriate strategy
    strategy = ProvisioningStrategyFactory.get_strategy(connection_string)

    # Step 1: Ensure database exists
    strategy.ensure_database_exists(connection_string, provisioning_connection_string)

    # Step 2 & 3: Ensure user exists and grant permissions (for server-based databases)
    if not connection_string.startswith("sqlite"):
        username, password = _parse_connection_url_for_user(connection_string)
        if username and password:
            strategy.ensure_user_exists(
                username, password, provisioning_connection_string
            )
            try:
                strategy.grant_permissions(
                    database_name, username, provisioning_connection_string
                )
            except Exception as exc:
                logger.warning(
                    "tenant.permissions.failed",
                    extra={"tenant": tenant.slug, "error": str(exc)},
                )

    # Step 4: Register connection in Django
    from multitenant.bootstrap import register_database_tenant_connection

    registered = register_database_tenant_connection(tenant)
    logger.info(
        "tenant.db.ready",
        extra={
            "tenant": tenant.slug,
            "alias": alias,
            "database": database_name,
            "engine": "sqlite" if connection_string.startswith("sqlite") else "server",
        },
    )
    return registered


def ensure_schema_exists(schema_name: str) -> bool:
    schema_name = str(schema_name or "").strip()
    if not schema_name:
        return False

    if connections["default"].vendor != "postgresql":
        raise SchemaProvisioningUnsupportedError()

    quoted_schema_name = connections["default"].ops.quote_name(schema_name)
    with connections["default"].cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {quoted_schema_name}")
    logger.info("tenant.schema.created_or_exists", extra={"schema": schema_name})
    return True


def migrate_schema_tenant(tenant: "Tenant") -> bool:
    if tenant.isolation_mode != tenant.IsolationMode.SCHEMA:
        return False

    schema_name = str(tenant.schema_name or "").strip()
    if not schema_name:
        return False

    if connections["default"].vendor != "postgresql":
        raise SchemaProvisioningUnsupportedError()

    activate_schema(schema_name)
    try:
        call_command("migrate", database="default", interactive=False, verbosity=0)
    finally:
        deactivate_schema()
    logger.info(
        "tenant.schema.migrated", extra={"tenant": tenant.slug, "schema": schema_name}
    )
    return True


def migrate_database_tenant(tenant: Any) -> int:
    alias = tenant if isinstance(tenant, str) else str(tenant.connection_alias or "")
    if not alias:
        return 0

    call_command("migrate", database=alias, interactive=False, verbosity=0)
    return 1


def provision_tenant(tenant: "Tenant") -> bool:
    if tenant.isolation_mode == tenant.IsolationMode.DATABASE:
        connection_string = tenant.get_connection_string()
        if not connection_string:
            return False

        # For SQLite, just ensure directory exists
        if connection_string.startswith("sqlite"):
            database_config = parse_connection_url(connection_string)
            database_name = str(database_config.get("NAME") or "").strip()
            if database_name and database_name != ":memory:":
                import os

                db_dir = os.path.dirname(database_name)
                if db_dir and not os.path.exists(db_dir):
                    os.makedirs(db_dir, exist_ok=True)
            logger.info(
                "tenant.sqlite.provisioned",
                extra={"tenant": tenant.slug, "database": database_name},
            )
        else:
            # For PostgreSQL/MySQL/etc
            provisioning_connection_string = (
                tenant.get_provisioning_connection_string() or connection_string
            )
            if not provisioning_connection_string:
                return False
            ensure_database_exists(connection_string, provisioning_connection_string)

        from multitenant.bootstrap import register_database_tenant_connection

        return register_database_tenant_connection(tenant)

    if tenant.isolation_mode == tenant.IsolationMode.SCHEMA:
        return ensure_schema_exists(str(tenant.schema_name or ""))

    return False


def migrate_tenant(tenant: "Tenant") -> bool:
    if tenant.isolation_mode == tenant.IsolationMode.DATABASE:
        return bool(migrate_database_tenant(tenant))

    if tenant.isolation_mode == tenant.IsolationMode.SCHEMA:
        return migrate_schema_tenant(tenant)

    return False


def provision_and_migrate_tenant(tenant: "Tenant") -> bool:
    provision_tenant(tenant)
    return migrate_tenant(tenant)


def delete_database_and_user(
    connection_string: str, provisioning_connection_string: str | None = None
) -> bool:
    """Delete database and user. Returns True if successful or resources don't exist."""
    try:
        import psycopg
        from psycopg import sql
    except ImportError:  # pragma: no cover
        logger.warning("psycopg not installed, cannot delete database resources")
        return False

    # Use provisioning connection or fall back to connection string with postgres db
    admin_connection_string = provisioning_connection_string or connection_string

    # Parse connection string to get database name and username
    database_name = _database_name_from_connection_url(connection_string)
    username, _ = _parse_connection_url_for_user(connection_string)

    if not database_name:
        logger.error(
            "tenant.delete.no_database_name",
            extra={"connection_string": connection_string[:50]},
        )
        return False

    target = _parse_postgres_url(admin_connection_string)
    if target is None:
        logger.error(
            "tenant.delete.invalid_admin_url",
            extra={"connection_string": admin_connection_string[:50]},
        )
        return False

    success = True

    # Step 1: Drop database if exists
    try:
        conn = psycopg.connect(_get_psycopg_connection_string(target))
        conn.autocommit = True
        with conn.cursor() as cur:
            # Terminate connections first
            cur.execute(
                """
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = %s
                AND pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            # Drop database
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(database_name)
                )
            )
        conn.close()
        logger.info("tenant.database.dropped", extra={"database": database_name})
    except Exception as exc:
        logger.error(
            "tenant.delete.database_failed",
            extra={"database": database_name, "error": str(exc)},
        )
        success = False

    # Step 2: Drop user if exists (and if different from admin user)
    if username and username != target.user:
        try:
            conn = psycopg.connect(_get_psycopg_connection_string(target))
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP USER IF EXISTS {}").format(sql.Identifier(username))
                )
            conn.close()
            logger.info("tenant.user.dropped", extra={"user": username})
        except Exception as exc:
            logger.error(
                "tenant.delete.user_failed", extra={"user": username, "error": str(exc)}
            )
            success = False

    return success
