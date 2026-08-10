"""Registry-backed lookup for physical broker endpoint contracts."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from .errors import EndpointNotFoundError, EndpointRegistryError
from .models import EndpointSpec, PayloadBinding


DEFAULT_REGISTRY_ROOT = Path(__file__).parents[1] / "registry"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise EndpointRegistryError(f"cannot read {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise EndpointRegistryError(f"{path}: document must be a mapping")
    return document


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise EndpointRegistryError(f"{where} must be a string-keyed mapping")
    return value


class EndpointRegistry:
    """Load endpoints, raw payload bindings, and broker capabilities from YAML."""

    def __init__(self, registry_root: Path | str | None = None):
        self.root = Path(registry_root) if registry_root is not None else DEFAULT_REGISTRY_ROOT
        self._capabilities = self._load_capabilities()
        self._endpoints = self._load_endpoints()

    def _load_capabilities(self) -> dict[str, tuple[str, ...]]:
        path = self.root / "capabilities.yaml"
        document = _load_yaml(path)
        result: dict[str, tuple[str, ...]] = {}
        for broker, raw_value in document.items():
            if not isinstance(broker, str):
                raise EndpointRegistryError(f"{path}: broker names must be strings")
            if isinstance(raw_value, dict):
                raw_capabilities = raw_value.get("capabilities", [])
            else:
                raw_capabilities = raw_value
            if not isinstance(raw_capabilities, list) or any(
                not isinstance(item, str) for item in raw_capabilities
            ):
                raise EndpointRegistryError(
                    f"{path}: capabilities for {broker!r} must be a list of strings"
                )
            result[broker] = tuple(raw_capabilities)
        return result

    def _load_endpoints(self) -> dict[tuple[str, str, str], EndpointSpec]:
        result: dict[tuple[str, str, str], EndpointSpec] = {}
        endpoint_paths = sorted(self.root.glob("*/*/endpoints.yaml"))
        if not endpoint_paths:
            raise EndpointRegistryError(f"{self.root}: no endpoints.yaml files found")

        for endpoint_path in endpoint_paths:
            endpoint_doc = _load_yaml(endpoint_path)
            mapping_path = endpoint_path.with_name("mappings.yaml")
            mapping_doc = _load_yaml(mapping_path)
            broker = endpoint_doc.get("broker")
            origin = endpoint_doc.get("origin")
            if not isinstance(broker, str) or not isinstance(origin, str):
                raise EndpointRegistryError(
                    f"{endpoint_path}: broker and origin must be strings"
                )
            if mapping_doc.get("broker") != broker or mapping_doc.get("origin") != origin:
                raise EndpointRegistryError(
                    f"{mapping_path}: broker/origin do not match endpoints.yaml"
                )
            if broker not in self._capabilities:
                raise EndpointRegistryError(
                    f"{endpoint_path}: broker {broker!r} is absent from capabilities.yaml"
                )

            endpoint_defs = _mapping(endpoint_doc.get("endpoints"), f"{endpoint_path}: endpoints")
            payload_defs = _mapping(mapping_doc.get("payloads"), f"{mapping_path}: payloads")
            mappings = _mapping(mapping_doc.get("mappings"), f"{mapping_path}: mappings")

            payloads_by_endpoint: dict[str, list[PayloadBinding]] = defaultdict(list)
            payload_endpoint: dict[str, str] = {}
            for payload_name, raw_payload in payload_defs.items():
                payload = _mapping(raw_payload, f"{mapping_path}: payload {payload_name!r}")
                endpoint_name = payload.get("endpoint", payload_name)
                payload_path = payload.get("path")
                if not isinstance(endpoint_name, str) or endpoint_name not in endpoint_defs:
                    raise EndpointRegistryError(
                        f"{mapping_path}: payload {payload_name!r} has unknown endpoint"
                    )
                if not isinstance(payload_path, str):
                    raise EndpointRegistryError(
                        f"{mapping_path}: payload {payload_name!r} path must be a string"
                    )
                payload_endpoint[payload_name] = endpoint_name
                payloads_by_endpoint[endpoint_name].append(PayloadBinding(payload_name, payload_path))

            semantic_paths_by_endpoint: dict[str, set[str]] = defaultdict(set)
            for semantic_path, raw_references in mappings.items():
                if not isinstance(raw_references, list):
                    raise EndpointRegistryError(
                        f"{mapping_path}: mapping {semantic_path!r} must be a list"
                    )
                for reference in raw_references:
                    if not isinstance(reference, str) or "#" not in reference:
                        raise EndpointRegistryError(
                            f"{mapping_path}: invalid raw reference {reference!r}"
                        )
                    payload_name = reference.split("#", 1)[0]
                    try:
                        endpoint_name = payload_endpoint[payload_name]
                    except KeyError as exc:
                        raise EndpointRegistryError(
                            f"{mapping_path}: unknown payload in {reference!r}"
                        ) from exc
                    semantic_paths_by_endpoint[endpoint_name].add(semantic_path)

            defaults = _mapping(
                endpoint_doc.get("transport_defaults"),
                f"{endpoint_path}: transport_defaults",
            )
            for name, raw_endpoint in endpoint_defs.items():
                endpoint = _mapping(raw_endpoint, f"{endpoint_path}: endpoint {name!r}")
                transport = dict(defaults)
                transport.update(
                    _mapping(endpoint.get("transport"), f"{endpoint_path}: endpoint transport")
                )
                fixed_params = dict(_mapping(defaults.get("fixed_params"), "fixed_params"))
                fixed_params.update(_mapping(transport.get("fixed_params"), "fixed_params"))

                raw_method = endpoint.get("method", transport.get("method"))
                method = str(raw_method) if raw_method is not None else None
                kind = transport.get("kind")
                if kind is None:
                    kind = "python" if method and method.lower() == "python" else "rest"
                if not isinstance(kind, str):
                    raise EndpointRegistryError(
                        f"{endpoint_path}: endpoint {name!r} transport kind must be a string"
                    )
                raw_path = endpoint.get("path")
                path = str(raw_path) if raw_path is not None else None
                base_url = endpoint_doc.get("baseurl", endpoint_doc.get("base_url"))
                if base_url is not None and not isinstance(base_url, str):
                    raise EndpointRegistryError(f"{endpoint_path}: baseurl must be a string")
                params = _mapping(
                    endpoint.get("params"), f"{endpoint_path}: endpoint {name!r} params"
                )
                operation_types = endpoint.get("operation_types", [])
                if not isinstance(operation_types, list) or any(
                    not isinstance(item, str) for item in operation_types
                ):
                    raise EndpointRegistryError(
                        f"{endpoint_path}: endpoint {name!r} operation_types must be strings"
                    )
                key = (broker, origin, name)
                if key in result:
                    raise EndpointRegistryError(f"duplicate endpoint {'/'.join(key)}")
                result[key] = EndpointSpec(
                    broker=broker,
                    origin=origin,
                    name=name,
                    transport_kind=kind,
                    method=method,
                    path=path,
                    base_url=base_url,
                    params=params,
                    fixed_params=fixed_params,
                    operation_types=tuple(operation_types),
                    payloads=tuple(sorted(payloads_by_endpoint[name], key=lambda item: item.name)),
                    semantic_paths=tuple(sorted(semantic_paths_by_endpoint[name])),
                )
        return result

    def get(self, broker: str, origin: str, endpoint: str) -> EndpointSpec:
        try:
            return self._endpoints[(broker, origin, endpoint)]
        except KeyError as exc:
            raise EndpointNotFoundError(
                f"unknown endpoint {broker}/{origin}/{endpoint}"
            ) from exc

    def capabilities_for(self, broker: str) -> tuple[str, ...]:
        return self._capabilities.get(broker, ())

    def endpoints_for(self, broker: str, origin: str) -> tuple[EndpointSpec, ...]:
        return tuple(
            spec
            for key, spec in sorted(self._endpoints.items())
            if key[:2] == (broker, origin)
        )


__all__ = ["DEFAULT_REGISTRY_ROOT", "EndpointRegistry"]
