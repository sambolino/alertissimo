"""Credential lookup and safe header construction."""
from __future__ import annotations

import os
from collections.abc import Mapping

from .errors import CredentialError

SECRET_HEADERS = {"authorization", "proxy-authorization", "x-api-key", "api-key"}


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key: "<redacted>" if key.lower() in SECRET_HEADERS else value
        for key, value in headers.items()
    }


class EnvironmentCredentials:
    """Resolve registered headers from explicit values, then environment variables."""

    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._values = dict(values or {})

    def headers_for(self, broker: str, required: Mapping[str, object]) -> dict[str, str]:
        result: dict[str, str] = {}
        for header, definition in required.items():
            env_name = f"ALERTISSIMO_{broker}_{header}".upper().replace("-", "_")
            value = self._values.get(header) or self._values.get(env_name) or os.getenv(env_name)
            is_required = isinstance(definition, Mapping) and definition.get("required", False)
            if value is None and is_required:
                raise CredentialError(f"missing required header {header!r} for {broker}")
            if value is not None:
                result[header] = value
        return result
