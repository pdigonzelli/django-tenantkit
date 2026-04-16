"""
JWT Authentication Helpers for Multi-Tenant Applications

This module provides optional helpers for integrating JWT authentication
with django-tenantkit. It is designed to be backend-agnostic and works
with any JWT library (simplejwt, Djoser, Keycloak, Auth0, etc.).

Usage:
------
1. Add tenant_slug to your JWT claims using TenantClaimsMixin
2. Validate tokens with TenantTokenValidator
3. Use TenantJWTAuthentication in DRF views

Example with djangorestframework-simplejwt:
-------------------------------------------
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from tenantkit.auth import TenantClaimsMixin

class TenantTokenObtainPairSerializer(TenantClaimsMixin, TokenObtainPairSerializer):
    pass

Example with DRF views:
-----------------------
from rest_framework.views import APIView
from tenantkit.auth import TenantJWTAuthentication

class MyView(APIView):
    authentication_classes = [TenantJWTAuthentication]
    # ...
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured

try:
    from rest_framework.authentication import BaseAuthentication
    from rest_framework.exceptions import AuthenticationFailed
except ImportError as e:
    raise ImportError(
        "djangorestframework is required to use tenantkit.auth. "
        "Install it with: pip install djangorestframework"
    ) from e

from tenantkit.core.context import get_current_tenant


class TenantClaimsMixin:
    """
    Mixin to add tenant_slug to JWT token claims.

    Use this with your JWT serializer to automatically include
    the current tenant in the token payload.

    Example:
        class MyTokenSerializer(TenantClaimsMixin, TokenObtainPairSerializer):
            pass
    """

    def get_token(self, user: Any) -> Any:
        """Add tenant_slug to token claims."""
        token = super().get_token(user)  # type: ignore[misc]

        # Get current tenant from context
        tenant = get_current_tenant()
        if tenant:
            token["tenant_slug"] = tenant.slug

        return token


class TenantTokenValidator:
    """
    Validates that the tenant in the JWT token matches the current request tenant.

    This prevents a token issued for Tenant A from being used to access Tenant B.
    """

    def validate_tenant(self, token_data: dict[str, Any], request: Any) -> None:
        """
        Validate tenant claim in token against current tenant.

        Args:
            token_data: Decoded JWT payload
            request: DRF request object

        Raises:
            AuthenticationFailed: If tenant mismatch or missing claim
        """
        token_tenant = token_data.get("tenant_slug")

        if not token_tenant:
            raise AuthenticationFailed(
                "Token does not contain tenant information. "
                "Ensure TenantClaimsMixin is used when generating tokens."
            )

        current_tenant = get_current_tenant()

        if not current_tenant:
            raise AuthenticationFailed(
                "No tenant context available. Ensure TenantMiddleware is installed."
            )

        if token_tenant != current_tenant.slug:
            raise AuthenticationFailed(
                f"Token is not valid for tenant '{current_tenant.slug}'. "
                f"Token was issued for tenant '{token_tenant}'."
            )


class TenantJWTAuthentication(BaseAuthentication):
    """
    DRF authentication class that wraps any JWT backend with tenant validation.

    This class automatically validates that the JWT token's tenant_slug claim
    matches the current request's tenant.

    This is a foundation class that defers concrete JWT backend integration
    to a future phase. It accepts an optional backend instance for testing
    or future injection.

    Usage:
        # In your DRF view or viewset
        class MyView(APIView):
            authentication_classes = [TenantJWTAuthentication]

    Configuration:
        Set TENANTKIT_JWT_BACKEND in settings.py to specify which JWT
        authentication backend to use (future phase):

        TENANTKIT_JWT_BACKEND = "rest_framework_simplejwt.authentication.JWTAuthentication"
    """

    def __init__(self, backend: Any | None = None) -> None:
        """
        Initialize with optional JWT backend.

        Args:
            backend: Optional JWT authentication backend instance.
                     If not provided, will attempt to load from settings.
        """
        super().__init__()
        self.jwt_backend = backend
        self.validator = TenantTokenValidator()

        # If no backend provided, check settings
        if self.jwt_backend is None:
            from django.conf import settings

            backend_path = getattr(settings, "TENANTKIT_JWT_BACKEND", None)

            if backend_path:
                from django.utils.module_loading import import_string

                try:
                    backend_class = import_string(backend_path)
                    self.jwt_backend = backend_class()
                except ImportError as e:
                    raise ImproperlyConfigured(
                        f"Could not import JWT backend '{backend_path}'. "
                        f"Make sure the package is installed. Error: {e}"
                    ) from e

    def authenticate(self, request: Any) -> tuple[Any, Any] | None:
        """
        Authenticate request using JWT backend and validate tenant.

        Returns:
            Tuple of (user, token) if authentication succeeds
            None if no authentication credentials provided

        Raises:
            AuthenticationFailed: If authentication or tenant validation fails
            ImproperlyConfigured: If no backend is configured
        """
        # Check if backend is configured
        if self.jwt_backend is None:
            raise AuthenticationFailed(
                "No JWT backend configured. Set TENANTKIT_JWT_BACKEND in settings "
                "or provide a backend instance. Concrete JWT backend integration "
                "is deferred to a future phase."
            )

        # Delegate to JWT backend
        result = self.jwt_backend.authenticate(request)

        if result is None:
            return None

        user, token = result

        # Skip tenant validation for anonymous users
        if isinstance(user, AnonymousUser):
            return result

        # Validate tenant claim
        # Note: Different JWT backends expose token data differently
        # Try to get it from the token object or decode it
        token_data = self._get_token_data(token)
        self.validator.validate_tenant(token_data, request)

        return result

    def _get_token_data(self, token: Any) -> dict[str, Any]:
        """
        Extract token payload data from token object.

        Different JWT libraries use different token representations.
        This method handles the most common cases.

        Args:
            token: Token object from JWT backend

        Returns:
            Dictionary containing token payload data

        Raises:
            AuthenticationFailed: If token format is not supported
        """
        # Case 1: Token has a payload attribute (e.g., simplejwt)
        if hasattr(token, "payload"):
            return dict(token.payload)

        # Case 2: Token is already a dict
        if isinstance(token, dict):
            return token

        # Case 3: Unsupported token representation
        # Concrete token extraction for other formats is deferred to future phase
        raise AuthenticationFailed(
            f"Unsupported token representation: {type(token).__name__}. "
            "Concrete token extraction for this backend is deferred to a future phase. "
            "Supported formats: objects with .payload attribute, dict."
        )

    def authenticate_header(self, request: Any):  # pyright: ignore[reportIncompatibleMethodOverride]
        """
        Return WWW-Authenticate header value.

        Args:
            request: DRF request object

        Returns:
            WWW-Authenticate header value
        """
        # If backend exists and has authenticate_header, delegate to it
        if self.jwt_backend and hasattr(self.jwt_backend, "authenticate_header"):
            return self.jwt_backend.authenticate_header(request)

        # Default to Bearer
        return "Bearer"
