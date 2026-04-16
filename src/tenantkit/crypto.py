from __future__ import annotations

import os
import shutil
import subprocess

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_OPENSSL_ARGS_ENCRYPT = [
    "enc",
    "-aes-256-cbc",
    "-pbkdf2",
    "-iter",
    "200000",
    "-md",
    "sha256",
    "-salt",
    "-a",
    "-A",
]

_OPENSSL_ARGS_DECRYPT = [
    "enc",
    "-d",
    "-aes-256-cbc",
    "-pbkdf2",
    "-iter",
    "200000",
    "-md",
    "sha256",
    "-salt",
    "-a",
    "-A",
]


def _tenant_key() -> str:
    key = getattr(settings, "TENANT_ENCRYPTION_KEY", None)
    if not key:
        raise ImproperlyConfigured(
            "TENANT_ENCRYPTION_KEY is required for tenant encryption."
        )
    return str(key)


def _openssl(command: list[str], payload: str) -> str:
    if shutil.which("openssl") is None:
        raise ImproperlyConfigured("openssl is required for tenant encryption.")

    env = os.environ.copy()
    env["TENANT_ENCRYPTION_KEY"] = _tenant_key()

    result = subprocess.run(
        ["openssl", *command, "-pass", "env:TENANT_ENCRYPTION_KEY"],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    if result.returncode != 0:
        raise ImproperlyConfigured((result.stderr or "").strip() or "openssl failed")

    return (result.stdout or "").strip()


def encrypt_text(plain_text: str) -> str:
    return _openssl(_OPENSSL_ARGS_ENCRYPT, plain_text)


def decrypt_text(cipher_text: str) -> str:
    return _openssl(_OPENSSL_ARGS_DECRYPT, cipher_text)
