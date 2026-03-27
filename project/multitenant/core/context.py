from __future__ import annotations

from contextvars import ContextVar
from typing import Any

# Request-scoped context for the active tenant and strategy.
current_tenant: ContextVar[Any | None] = ContextVar("current_tenant", default=None)
current_strategy: ContextVar[Any | None] = ContextVar("current_strategy", default=None)


def set_current_tenant(tenant: Any) -> None:
    current_tenant.set(tenant)


def get_current_tenant() -> Any | None:
    return current_tenant.get()


def clear_current_tenant() -> None:
    current_tenant.set(None)


def set_current_strategy(strategy: Any) -> None:
    current_strategy.set(strategy)


def get_current_strategy() -> Any | None:
    return current_strategy.get()


def clear_current_strategy() -> None:
    current_strategy.set(None)
