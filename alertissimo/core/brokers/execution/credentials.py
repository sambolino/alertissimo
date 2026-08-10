"""Credential resolution without exposing secrets in execution metadata."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol
import tomllib

from .errors import MissingCredentialError


DEFAULT_SECRETS_PATH = Path(__file__).parents[4] / ".streamlit" / "secrets.toml"


def _credential_name(broker: str, origin: str) -> str:
    return f"{broker}_{origin}_TOKEN".upper()


def _authorization_headers(broker: str, token: str) -> dict[str, str]:
    scheme = "Token" if broker.lower() == "lasair" else "Bearer"
    return {"Authorization": f"{scheme} {token}"}


class CredentialResolver(Protocol):
    def resolve(
        self,
        *,
        broker: str,
        origin: str,
        endpoint: str,
    ) -> Mapping[str, str]:
        ...


class EnvironmentCredentialResolver:
    """Resolve ``BROKER_ORIGIN_TOKEN`` from the process environment."""

    def __init__(self, environ: Mapping[str, str] | None = None):
        self._environ = os.environ if environ is None else environ

    def resolve(
        self,
        *,
        broker: str,
        origin: str,
        endpoint: str,
    ) -> Mapping[str, str]:
        name = _credential_name(broker, origin)
        token = self._environ.get(name)
        if not token:
            raise MissingCredentialError(f"missing credential {name}")
        return _authorization_headers(broker, token)


class TomlCredentialResolver:
    """Resolve broker tokens from a local TOML secrets file."""

    def __init__(self, path: Path | str = DEFAULT_SECRETS_PATH):
        self.path = Path(path)

    def resolve(
        self,
        *,
        broker: str,
        origin: str,
        endpoint: str,
    ) -> Mapping[str, str]:
        name = _credential_name(broker, origin)
        try:
            with self.path.open("rb") as stream:
                secrets = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise MissingCredentialError(f"cannot read credentials from {self.path}") from exc
        token = secrets.get(name)
        if not isinstance(token, str) or not token:
            raise MissingCredentialError(f"missing credential {name} in {self.path}")
        return _authorization_headers(broker, token)


class ChainedCredentialResolver:
    """Use the first configured credential source."""

    def __init__(self, resolvers: Sequence[CredentialResolver]):
        self._resolvers = tuple(resolvers)

    def resolve(
        self,
        *,
        broker: str,
        origin: str,
        endpoint: str,
    ) -> Mapping[str, str]:
        failures: list[str] = []
        for resolver in self._resolvers:
            try:
                return resolver.resolve(broker=broker, origin=origin, endpoint=endpoint)
            except MissingCredentialError as exc:
                failures.append(str(exc))
        raise MissingCredentialError("; ".join(failures) or "no credential resolvers configured")


def default_credential_resolver() -> ChainedCredentialResolver:
    return ChainedCredentialResolver([
        EnvironmentCredentialResolver(),
        TomlCredentialResolver(),
    ])


__all__ = [
    "ChainedCredentialResolver",
    "CredentialResolver",
    "DEFAULT_SECRETS_PATH",
    "EnvironmentCredentialResolver",
    "TomlCredentialResolver",
    "default_credential_resolver",
]
