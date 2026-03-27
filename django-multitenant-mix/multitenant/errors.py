from __future__ import annotations


class MultitenantError(Exception):
    code = "MULTITENANT_ERROR"
    status_code = 400

    def __init__(
        self, message: str, *, code: str | None = None, status_code: int | None = None
    ):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class ProvisioningError(MultitenantError):
    code = "PROVISIONING_ERROR"


class SchemaProvisioningUnsupportedError(ProvisioningError):
    code = "SCHEMA_PROVISIONING_UNSUPPORTED"

    def __init__(self) -> None:
        super().__init__(
            "Schema provisioning is not available on this database backend. Use PostgreSQL for shared/default to provision schema tenants.",
            code=self.code,
            status_code=400,
        )
