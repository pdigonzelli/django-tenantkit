from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TenantStrategy(ABC):
    """Base contract for tenant isolation strategies."""

    @abstractmethod
    def activate(self, tenant: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def deactivate(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def db_for_read(self, model: Any, **hints: Any) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def db_for_write(self, model: Any, **hints: Any) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def allow_migrate(
        self, db: str, app_label: str, model_name: str | None = None, **hints: Any
    ) -> bool | None:
        raise NotImplementedError
