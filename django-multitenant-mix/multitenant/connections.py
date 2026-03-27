from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlparse, urlunparse

from secrets import token_urlsafe

from django.conf import settings


DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = 5432


def get_default_db_engine() -> str:
    """Get the default database engine from settings or return 'sqlite'."""
    from django.conf import settings

    return getattr(settings, "TENANT_DEFAULT_DB_ENGINE", "sqlite")


def normalize_identifier(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def build_schema_name(slug: str) -> str:
    return f"tenant_{normalize_identifier(slug)}"[:63]


def build_connection_alias(slug: str) -> str:
    return f"tenant_{normalize_identifier(slug)}"[:100]


def build_connection_url(
    alias: str,
    *,
    scheme: str | None = None,
    host: str = DEFAULT_DB_HOST,
    port: int = DEFAULT_DB_PORT,
    database_name: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> str:
    if scheme is None:
        scheme = get_default_db_engine()
    scheme = scheme.lower()
    if scheme in {"sqlite", "sqlite3"}:
        if database_name:
            # Modo manual: respeta exactamente lo que el usuario ingresó
            sqlite_path = Path(database_name)
            if not sqlite_path.is_absolute():
                # Si es relativo, lo deja relativo al directorio de trabajo
                return f"sqlite:///{sqlite_path.as_posix()}"
            return f"sqlite:///{sqlite_path.as_posix().lstrip('/')}"

        # Modo auto: genera en tenant_dbs/
        tenant_dbs_dir = Path(settings.BASE_DIR) / "tenant_dbs"
        tenant_dbs_dir.mkdir(parents=True, exist_ok=True)
        sqlite_path = tenant_dbs_dir / f"{normalize_identifier(alias)}.sqlite3"
        return f"sqlite:///{sqlite_path.as_posix().lstrip('/')}"

    username = username or alias
    password = password or token_urlsafe(32)
    database_name = database_name or alias

    netloc = f"{quote(username)}:{quote(password)}@{host}:{port}"
    path = f"/{quote(database_name)}"
    return urlunparse((scheme, netloc, path, "", "", ""))


def parse_connection_url(url: str) -> dict[str, object]:
    if "://" not in url:
        path = Path(url)
        if not path.is_absolute():
            name = url
        else:
            name = str(path)
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": name,
            "USER": "",
            "PASSWORD": "",
            "HOST": "",
            "PORT": "",
            "OPTIONS": {},
            "ATOMIC_REQUESTS": False,
            "AUTOCOMMIT": True,
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": False,
            "TIME_ZONE": None,
        }

    parsed = urlparse(url)
    options = dict(parse_qsl(parsed.query))

    scheme = parsed.scheme.lower()
    if scheme in {"sqlite", "sqlite3"}:
        raw_path = parsed.path or ""
        if raw_path in {"/:memory:", ":memory:"}:
            name = ":memory:"
        elif raw_path.startswith("//"):
            name = "/" + raw_path.lstrip("/")
        else:
            name = raw_path.lstrip("/")

        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": name,
            "USER": "",
            "PASSWORD": "",
            "HOST": "",
            "PORT": "",
            "OPTIONS": options,
            "ATOMIC_REQUESTS": False,
            "AUTOCOMMIT": True,
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": False,
            "TIME_ZONE": None,
        }

    engine_map = {
        "postgres": "django.db.backends.postgresql",
        "postgresql": "django.db.backends.postgresql",
        "mysql": "django.db.backends.mysql",
        "mariadb": "django.db.backends.mysql",
    }
    engine = engine_map.get(scheme, "django.db.backends.sqlite3")

    return {
        "ENGINE": engine,
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
        "OPTIONS": options,
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "TIME_ZONE": None,
    }
