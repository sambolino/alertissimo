"""Registry-driven endpoint executor."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from time import perf_counter
from typing import Any, Callable, Mapping

from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance

from .ids import new_internal_execution_id
from .models import EndpointSpec, ExecutionResult, TransportResult
from .registry import EndpointRegistry
from .transports import PythonClientTransport, RestTransport


class MissingEndpointCredentialError(RuntimeError):
    """A required physical endpoint credential could not be resolved."""


class EndpointPaginationError(RuntimeError):
    """A declared page-based endpoint could not be exhausted safely."""


class RegistryEndpointExecutor:
    # Auto-pagination is an execution concern, not a semantic limit. Use large
    # transport batches so a complete semantic search does not devolve into the
    # provider's often tiny interactive default (ALeRCE uses 10 rows/page).
    # Individual endpoint contracts may override this with ``auto_page_size`` on
    # their page_size parameter.
    _DEFAULT_AUTO_PAGE_SIZE = 1_000
    _MAX_AUTO_PAGES = 100

    def __init__(
        self,
        registry: EndpointRegistry | None = None,
        transports: Mapping[str, Any] | None = None,
        execution_id_factory: Callable[[], InternalExecutionId] = new_internal_execution_id,
    ) -> None:
        self.registry = registry or EndpointRegistry()
        self.transports = {
            "rest": RestTransport(),
            "python_client": PythonClientTransport(),
            **dict(transports or {}),
        }
        self.execution_id_factory = execution_id_factory

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
            if contract.get("required") is True and name not in validated:
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

    @classmethod
    def _auto_paginated_params(
        cls,
        spec: EndpointSpec,
        params: Mapping[str, Any],
        *,
        caller_supplied_page: bool,
    ) -> dict[str, Any]:
        """Choose an efficient physical page size for transparent auto-pagination.

        Provider defaults are intentionally left truthful in endpoint declarations.
        When Alertissimo owns pagination, however, using a provider's interactive
        default of only a handful of rows can require hundreds of serial calls. The
        page-size contract may declare ``auto_page_size``; otherwise the executor's
        conservative batch default is used. A caller selecting an explicit page keeps
        the provider's normal one-page semantics and is not rewritten here.
        """

        prepared = dict(params)
        page_parameters = cls._page_parameters(spec)
        if caller_supplied_page or page_parameters is None:
            return prepared
        _, page_size_param = page_parameters
        if page_size_param is None or page_size_param in prepared:
            return prepared

        contract = spec.params.get(page_size_param) or {}
        auto_page_size = contract.get("auto_page_size", cls._DEFAULT_AUTO_PAGE_SIZE)
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
                if len(results) >= self._MAX_AUTO_PAGES:
                    raise EndpointPaginationError(
                        f"automatic pagination exceeded {self._MAX_AUTO_PAGES} pages for "
                        f"{spec.broker}/{spec.origin}/{spec.endpoint}; refuse to continue "
                        "an unexpectedly large physical scan"
                    )
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
                if len(results) >= self._MAX_AUTO_PAGES:
                    raise EndpointPaginationError(
                        f"automatic pagination exceeded {self._MAX_AUTO_PAGES} pages for "
                        f"{spec.broker}/{spec.origin}/{spec.endpoint}; refuse to continue "
                        "an unexpectedly large physical scan"
                    )
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
        resolved_headers = self._resolved_headers(spec, headers)
        execution_id = self.execution_id_factory()
        started = datetime.now(timezone.utc)
        timer = perf_counter()
        transport = self.transports[spec.transport_kind]
        transport_result = self._execute_with_pagination(
            transport,
            spec,
            validated,
            resolved_headers,
            caller_supplied_page=caller_supplied_page,
        )
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
