#!/usr/bin/env python3
"""Offline acceptance check for declarative physical-execution safety policy.

No provider API is contacted. A fake paginated endpoint keeps returning full pages;
the real RegistryEndpointExecutor must stop exactly at the configured automatic-page
limit and report the declarative policy source.
"""

from __future__ import annotations

from alertissimo.data_layer.execution import (
    EndpointSpec,
    ExecutionPolicyLimitError,
    RegistryEndpointExecutor,
    TransportResult,
    load_execution_policy,
)


class _Registry:
    def __init__(self, spec: EndpointSpec) -> None:
        self.spec = spec

    def resolve(self, broker: str, origin: str, endpoint: str) -> EndpointSpec:
        expected = (self.spec.broker, self.spec.origin, self.spec.endpoint)
        actual = (broker, origin, endpoint)
        if actual != expected:
            raise KeyError(actual)
        return self.spec


class _EndlessPagedTransport:
    name = "offline-policy-check"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute(self, spec, params, headers=None) -> TransportResult:
        call = dict(params)
        self.calls.append(call)
        page_size = int(call["page_size"])
        page = int(call.get("page", 1))
        return TransportResult(
            payload=[{"page": page, "row": index} for index in range(page_size)],
            method="GET",
            url="offline://execution-policy-check",
            status_code=200,
        )


def main() -> int:
    policy = load_execution_policy()
    print("=== ALERTISSIMO EXECUTION POLICY CHECK ===")
    print(f"policy:                 {policy.source_path}")
    print(f"default_auto_page_size: {policy.default_auto_page_size}")
    print(f"max_auto_pages:         {policy.max_auto_pages}")

    spec = EndpointSpec(
        broker="offline",
        origin="test",
        endpoint="endless_pages",
        transport_kind="rest",
        params={
            "page": {"role": "pagination"},
            "page_size": {"role": "pagination"},
        },
        method="GET",
        url="offline://execution-policy-check",
    )
    transport = _EndlessPagedTransport()
    executor = RegistryEndpointExecutor(
        registry=_Registry(spec),
        transports={"rest": transport},
        policy=policy,
    )

    try:
        executor.execute(spec.broker, spec.origin, spec.endpoint)
    except ExecutionPolicyLimitError as error:
        if len(transport.calls) != policy.max_auto_pages:
            raise RuntimeError(
                "policy limit fired after the wrong number of physical calls: "
                f"{len(transport.calls)} != {policy.max_auto_pages}"
            ) from error
        if str(policy.source_path) not in str(error):
            raise RuntimeError("policy-limit error does not expose its policy source") from error
        print(f"physical calls before stop: {len(transport.calls)}")
        print(f"PASS: {error}")
        return 0

    raise RuntimeError("executor failed to enforce max_auto_pages")


if __name__ == "__main__":
    raise SystemExit(main())
