"""Registry-driven endpoint executor."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from time import perf_counter
from typing import Any, Callable, Mapping

from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance

from .ids import new_internal_execution_id
from .models import EndpointSpec, ExecutionResult, TransportResult
from .policy import ExecutionPolicy, load_execution_policy
from .registry import EndpointRegistry
from .transports import PythonClientTransport, RestTransport


class MissingEndpointCredentialError(RuntimeError):
    """A required physical endpoint credential could not be resolved."""


class EndpointPaginationError(RuntimeError):
    """A declared paginated or capped result could not be verified safely."""


class ExecutionPolicyLimitError(EndpointPaginationError):
    """A physical execution reached a configured operational safety limit."""


class RegistryEndpointExecutor:
    def __init__(
        self,
        registry: EndpointRegistry | None = None,
        transports: Mapping[str, Any] | None = None,
        execution_id_factory: Callable[[], InternalExecutionId] = new_internal_execution_id,
        policy: ExecutionPolicy | None = None,
    ) -> None:
        self.registry = registry or EndpointRegistry()
        self.transports = {
            "rest": RestTransport(),
            "python_client": PythonClientTransport(),
            **dict(transports or {}),
        }
        self.execution_id_factory = execution_id_factory
        self.policy = policy or load_execution_policy()

    @staticmethod
    def _validated_params(
        spec: EndpointSpec, supplied: Mapping[str, Any]
    ) -> dict[str, Any]:
        unknown = set(supplied) - set(spec.params)
        if unknown:
            raise ValueError(f"unknown endpoint parameters: {', '.join(sorted(unknown))}")
        validated = dict(supplied)
        for name, contract in spec.params.items():
            contract = contract or {}
            if name not in validated and "default" in contract:
                validated[name] = contract["default"]
            if contract.get("required") is True and name not in validated and name not in spec.fixed_params:
                raise ValueError(f"missing required endpoint parameter: {name}")
        # Fixed values are executor-owned and are deliberately applied last.
        validated.update(spec.fixed_params)
        return validated

    @staticmethod
    def _resolved_headers(
        spec: EndpointSpec, supplied: Mapping[str, str] | None
    ) -> dict[str, str] | None:
        """Resolve physical header contracts, with caller values taking priority."""
        resolved = dict(supplied or {})
        for name, contract in spec.headers.items():
            contract = contract or {}
            if name in resolved:
                continue
            environment_variable = contract.get("environment_variable")
            if environment_variable:
                value = os.environ.get(environment_variable)
                if value:
                    # Only raw environment values are supported. Formatting remains
                    # declarative in the endpoint contract.
                    if contract.get("environment_value") != "raw":
                        raise ValueError(
                            f"unsupported environment value format for endpoint header: {name}"
                        )
                    resolved[name] = f"{contract.get('prefix', '')}{value}"
                    continue
            if contract.get("required") is True:
                raise MissingEndpointCredentialError(
                    f"missing required credential for {spec.broker}/{spec.origin}/"
                    f"{spec.endpoint} header {name}; set {environment_variable or 'the header explicitly'}"
                )
        return resolved or None

    @staticmethod
    def _page_parameters(spec: EndpointSpec) -> tuple[str, str | None] | None:
        """Return the declared conventional page and page-size parameters, if any.

        Endpoint contracts already mark transport-owned pagination parameters with
        ``role: pagination``.  The executor supports the common page/page_size form
        without promoting those physical controls into semantic WorkflowIR.
        """

        pagination = {
            name
            for name, raw_contract in spec.params.items()
            if (raw_contract or {}).get("role") == "pagination"
        }
        if "page" not in pagination:
            return None
        return "page", "page_size" if "page_size" in pagination else None

    @staticmethod
    def _offset_parameters(spec: EndpointSpec) -> tuple[str, str] | None:
        pagination = {
            name for name, contract in spec.params.items()
            if (contract or {}).get("role") == "pagination"
        }
        if not pagination.intersection({"offset", "limit"}):
            return None
        if not {"offset", "limit"} <= pagination or "page" in pagination:
            raise EndpointPaginationError(
                "offset pagination requires a declared limit/offset pair without page pagination"
            )
        return "offset", "limit"

    @staticmethod
    def _offset_controls(
        spec: EndpointSpec, params: Mapping[str, Any], *, explicit_offset: bool,
    ) -> tuple[int, int] | None:
        names = RegistryEndpointExecutor._offset_parameters(spec)
        if names is None or explicit_offset:
            return None
        offset_name, limit_name = names
        offset, limit = params.get(offset_name, 0), params.get(limit_name)
        if type(offset) is not int or offset < 0 or type(limit) is not int or limit <= 0:
            raise EndpointPaginationError("offset must be a non-negative integer and limit a positive integer")
        # Some APIs silently clamp a requested page according to account class.
        # A shorter page could then look exhausted. The declaration records a
        # universally safe auto-paging size, not a false absolute API maximum.
        ceiling = (spec.params[limit_name] or {}).get("auto_page_size_max")
        if ceiling is not None:
            if type(ceiling) is not int or ceiling <= 0:
                raise EndpointPaginationError("auto_page_size_max must be a positive integer")
            if limit > ceiling:
                raise EndpointPaginationError(
                    f"automatic offset pagination requires {limit_name} <= "
                    f"auto_page_size_max={ceiling}; the provider may clamp larger pages. "
                    "Use a safe page size, or select an explicit offset for one bounded response."
                )
        return offset, limit

    def _auto_paginated_params(
        self,
        spec: EndpointSpec,
        params: Mapping[str, Any],
        *,
        caller_supplied_page: bool,
    ) -> dict[str, Any]:
        """Choose an efficient physical page size for transparent auto-pagination.

        Provider defaults are intentionally left truthful in endpoint declarations.
        When Alertissimo owns pagination, however, using a provider's interactive
        default of only a handful of rows can require many serial calls. The
        page-size contract may declare ``auto_page_size``; otherwise the declarative
        execution policy supplies the global fallback. A caller selecting an explicit
        page keeps the provider's normal one-page semantics and is not rewritten here.
        """

        prepared = dict(params)
        page_parameters = self._page_parameters(spec)
        if caller_supplied_page or page_parameters is None:
            return prepared
        _, page_size_param = page_parameters
        if page_size_param is None or page_size_param in prepared:
            return prepared

        contract = spec.params.get(page_size_param) or {}
        auto_page_size = contract.get(
            "auto_page_size", self.policy.default_auto_page_size
        )
        if isinstance(auto_page_size, bool):
            raise EndpointPaginationError("auto_page_size must be a positive integer")
        try:
            auto_page_size = int(auto_page_size)
        except (TypeError, ValueError, OverflowError) as exc:
            raise EndpointPaginationError("auto_page_size must be a positive integer") from exc
        if auto_page_size <= 0:
            raise EndpointPaginationError("auto_page_size must be a positive integer")
        prepared[page_size_param] = auto_page_size
        return prepared

    @staticmethod
    def _call_transport(
        transport: Any,
        spec: EndpointSpec,
        params: Mapping[str, Any],
        headers: Mapping[str, str] | None,
    ) -> TransportResult:
        result = (
            transport.execute(spec, params, headers)
            if headers is not None
            else transport.execute(spec, params)
        )
        if not isinstance(result, TransportResult):
            raise TypeError("endpoint transports must return TransportResult")
        return result

    @staticmethod
    def _merge_transport_results(
        first: TransportResult,
        last: TransportResult,
        *,
        payload: Any,
        raw_size_bytes: int | None,
    ) -> TransportResult:
        """Represent one logical endpoint execution whose transport used pages."""

        return TransportResult(
            payload=payload,
            method=first.method or last.method,
            url=first.url or last.url,
            status_code=last.status_code if last.status_code is not None else first.status_code,
            content_type=first.content_type or last.content_type,
            sanitized_headers=first.sanitized_headers or last.sanitized_headers,
            raw_size_bytes=raw_size_bytes,
        )

    @staticmethod
    def _summed_raw_size(results: list[TransportResult]) -> int | None:
        sizes = [result.raw_size_bytes for result in results]
        return sum(size for size in sizes if size is not None) if any(
            size is not None for size in sizes
        ) else None

    def _policy_limit_error(self, spec: EndpointSpec) -> ExecutionPolicyLimitError:
        return ExecutionPolicyLimitError(
            "automatic pagination reached configured execution-policy limit "
            f"max_auto_pages={self.policy.max_auto_pages} for "
            f"{spec.broker}/{spec.origin}/{spec.endpoint}; policy source: "
            f"{self.policy.source_path}. Refine the query or deliberately change "
            "the physical execution policy; results are not silently truncated."
        )

    @staticmethod
    def _json_result_limit(
        spec: EndpointSpec, params: Mapping[str, Any],
    ) -> tuple[str, int] | None:
        """Read an opt-in ceiling for a non-paginated JSON array response.

        This detects saturation only. Fewer returned rows do not by themselves
        prove population completeness: provider-side grouping and post-filters
        still need separate admission evidence. Explicit raw export modes retain
        their physical one-response behavior and have no row-count guarantee.
        """
        names = [
            name for name, contract in spec.params.items()
            if (contract or {}).get("role") == "result_limit"
        ]
        if not names:
            return None
        if (
            len(names) != 1 or RegistryEndpointExecutor._page_parameters(spec)
            or RegistryEndpointExecutor._offset_parameters(spec)
        ):
            raise EndpointPaginationError(
                "result_limit requires one ceiling on a non-paginated JSON array"
            )
        name, = names
        value = params.get(name)
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            value = int(value)
        if type(value) is not int or value <= 0:
            raise EndpointPaginationError(f"result_limit parameter {name!r} must be a positive integer")
        if any(
            (contract or {}).get("role") == "output_format"
            and params.get(parameter) != "json"
            for parameter, contract in spec.params.items()
        ):
            return None
        return name, value

    @staticmethod
    def _check_result_limit(
        spec: EndpointSpec, result: TransportResult, limit: tuple[str, int] | None,
    ) -> None:
        if limit is None:
            return
        context = f"{spec.broker}/{spec.origin}/{spec.endpoint}"
        if not isinstance(result.payload, list):
            raise EndpointPaginationError(
                f"cannot verify result_limit for {context}: expected a JSON array"
            )
        name, ceiling = limit
        if len(result.payload) >= ceiling:
            raise EndpointPaginationError(
                f"incomplete result from {context}: returned {len(result.payload)} rows "
                f"at the physical ceiling {name}={ceiling}; completeness cannot be "
                "established. Narrow the time window or query; no successful "
                "partial result is returned."
            )

    def _execute_with_pagination(
        self,
        transport: Any,
        spec: EndpointSpec,
        params: Mapping[str, Any],
        headers: Mapping[str, str] | None,
        *,
        caller_supplied_page: bool,
    ) -> TransportResult:
        """Execute and exhaust a declared page-based result when the caller did not select one page.

        Providers expose two shapes used by current registry endpoints: a wrapper
        containing ``items`` plus ``next``/``has_next`` metadata, and a bare list
        where a client library has stripped that wrapper.  Both remain transport
        details.  Normalization receives one shape-compatible aggregate payload.
        """

        first = self._call_transport(transport, spec, params, headers)
        page_parameters = self._page_parameters(spec)
        if caller_supplied_page or page_parameters is None:
            return first

        page_param, page_size_param = page_parameters
        payload = first.payload
        results = [first]

        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            merged_items = list(payload["items"])
            current_payload = payload
            current_page = current_payload.get("page", 1)
            seen_pages = {current_page}

            while bool(current_payload.get("has_next")) or current_payload.get("next") is not None:
                if len(results) >= self.policy.max_auto_pages:
                    raise self._policy_limit_error(spec)
                next_page = current_payload.get("next")
                if next_page is None:
                    try:
                        next_page = int(current_page) + 1
                    except (TypeError, ValueError) as exc:
                        raise EndpointPaginationError(
                            "paginated response has has_next=true but no usable next page"
                        ) from exc
                if next_page in seen_pages:
                    raise EndpointPaginationError(
                        f"paginated response repeated page {next_page!r} for "
                        f"{spec.broker}/{spec.origin}/{spec.endpoint}"
                    )
                seen_pages.add(next_page)
                page_params = dict(params)
                page_params[page_param] = next_page
                page_result = self._call_transport(transport, spec, page_params, headers)
                if not isinstance(page_result.payload, dict) or not isinstance(
                    page_result.payload.get("items"), list
                ):
                    raise EndpointPaginationError(
                        "paginated endpoint changed payload shape between pages"
                    )
                results.append(page_result)
                current_payload = page_result.payload
                current_page = current_payload.get("page", next_page)
                merged_items.extend(current_payload["items"])

            merged = dict(payload)
            merged["items"] = merged_items
            if "next" in merged:
                merged["next"] = None
            if "has_next" in merged:
                merged["has_next"] = False
            return self._merge_transport_results(
                first,
                results[-1],
                payload=merged,
                raw_size_bytes=self._summed_raw_size(results),
            )

        if isinstance(payload, list):
            merged_items = list(payload)
            if not payload:
                return first

            declared_page_size = params.get(page_size_param) if page_size_param else None
            try:
                effective_page_size = (
                    int(declared_page_size)
                    if declared_page_size is not None
                    else len(payload)
                )
            except (TypeError, ValueError) as exc:
                raise EndpointPaginationError("page_size must be an integer") from exc
            if effective_page_size <= 0:
                raise EndpointPaginationError("page_size must be positive")
            if len(payload) < effective_page_size:
                return first

            page_number = 1
            previous_payload = payload
            while len(previous_payload) >= effective_page_size:
                if len(results) >= self.policy.max_auto_pages:
                    raise self._policy_limit_error(spec)
                page_number += 1
                page_params = dict(params)
                page_params[page_param] = page_number
                page_result = self._call_transport(transport, spec, page_params, headers)
                if not isinstance(page_result.payload, list):
                    raise EndpointPaginationError(
                        "paginated endpoint changed payload shape between pages"
                    )
                if page_result.payload and page_result.payload == previous_payload:
                    raise EndpointPaginationError(
                        f"paginated endpoint repeated page content at page {page_number}"
                    )
                results.append(page_result)
                previous_payload = page_result.payload
                merged_items.extend(previous_payload)
                if not previous_payload:
                    break

            return self._merge_transport_results(
                first,
                results[-1],
                payload=merged_items,
                raw_size_bytes=self._summed_raw_size(results),
            )

        return first

    def _execute_with_offsets(
        self, transport: Any, spec: EndpointSpec, params: Mapping[str, Any],
        headers: Mapping[str, str] | None, controls: tuple[int, int],
    ) -> TransportResult:
        """Exhaust a declared JSON-array offset query as one logical execution.

        Stable ordering and a consistent provider population remain caller/query
        obligations. Offset mechanics alone do not provide snapshot isolation.
        """
        offset, limit = controls
        results: list[TransportResult] = []
        merged: list[Any] = []
        while True:
            if len(results) >= self.policy.max_auto_pages:
                raise self._policy_limit_error(spec)
            page_params = {**params, "offset": offset}
            result = self._call_transport(transport, spec, page_params, headers)
            payload = result.payload
            if not isinstance(payload, list):
                raise EndpointPaginationError(
                    f"offset pagination expected a JSON array for "
                    f"{spec.broker}/{spec.origin}/{spec.endpoint} at offset {offset}"
                )
            if len(payload) > limit:
                raise EndpointPaginationError("offset response exceeded the requested limit")
            if payload and any(payload == prior.payload for prior in results):
                raise EndpointPaginationError(f"offset pagination repeated page content at offset {offset}")
            results.append(result)
            merged.extend(payload)
            if len(payload) < limit:
                return self._merge_transport_results(
                    results[0], result, payload=merged,
                    raw_size_bytes=self._summed_raw_size(results),
                )
            offset += limit

    def execute(
        self,
        broker: str,
        origin: str,
        endpoint: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ExecutionResult:
        spec = self.registry.resolve(broker, origin, endpoint)
        supplied = dict(params or {})
        validated = self._validated_params(spec, supplied)
        caller_supplied_page = "page" in supplied
        validated = self._auto_paginated_params(
            spec,
            validated,
            caller_supplied_page=caller_supplied_page,
        )
        explicit_offset = "offset" in supplied or "offset" in spec.fixed_params
        offset_controls = self._offset_controls(spec, validated, explicit_offset=explicit_offset)
        result_limit = self._json_result_limit(spec, validated)
        resolved_headers = self._resolved_headers(spec, headers)
        execution_id = self.execution_id_factory()
        started = datetime.now(timezone.utc)
        timer = perf_counter()
        transport = self.transports[spec.transport_kind]
        if offset_controls is not None:
            transport_result = self._execute_with_offsets(
                transport, spec, validated, resolved_headers, offset_controls,
            )
        else:
            transport_result = self._execute_with_pagination(
                transport,
                spec,
                validated,
                resolved_headers,
                caller_supplied_page=caller_supplied_page,
            )
        self._check_result_limit(spec, transport_result, result_limit)
        elapsed_ms = (perf_counter() - timer) * 1000
        finished = datetime.now(timezone.utc)
        provenance = InternalExecutionProvenance(
            internal_execution_id=execution_id,
            broker=spec.broker,
            origin=spec.origin,
            endpoint=spec.endpoint,
            params=dict(validated),
            status="success",
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            elapsed_ms=elapsed_ms,
            transport=getattr(transport, "name", spec.transport_kind),
            method=transport_result.method or spec.method,
            url=transport_result.url or spec.url,
            sanitized_headers=(
                {
                    **dict(transport_result.sanitized_headers or {}),
                    **{
                        name: "<redacted>"
                        for name in spec.headers
                        if resolved_headers is not None and name in resolved_headers
                    },
                }
                if transport_result.sanitized_headers is not None
                or resolved_headers is not None
                else None
            ),
            response_status_code=transport_result.status_code,
            response_content_type=transport_result.content_type,
            raw_size_bytes=transport_result.raw_size_bytes,
        )
        return ExecutionResult(payload=transport_result.payload, execution_provenance=provenance)


EndpointExecutor = RegistryEndpointExecutor
