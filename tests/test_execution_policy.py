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
        assert (broker, origin, endpoint) == (
            self.spec.broker,
            self.spec.origin,
            self.spec.endpoint,
        )
        return self.spec


class _EndlessPagedTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute(self, spec, params, headers=None) -> TransportResult:
        call = dict(params)
        self.calls.append(call)
        page_size = int(call["page_size"])
        page = int(call.get("page", 1))
        return TransportResult(
            payload=[{"page": page, "row": index} for index in range(page_size)]
        )


def _paginated_spec() -> EndpointSpec:
    return EndpointSpec(
        broker="offline",
        origin="test",
        endpoint="endless_pages",
        transport_kind="rest",
        params={
            "page": {"role": "pagination"},
            "page_size": {"role": "pagination"},
        },
    )


def test_default_execution_policy_is_loaded_from_yaml():
    policy = load_execution_policy()

    assert policy.default_auto_page_size == 1000
    assert policy.max_auto_pages == 3
    assert policy.source_path.name == "policy.yaml"


def test_executor_stops_at_declarative_auto_page_limit():
    policy = load_execution_policy()
    spec = _paginated_spec()
    transport = _EndlessPagedTransport()
    executor = RegistryEndpointExecutor(
        registry=_Registry(spec),
        transports={"rest": transport},
        policy=policy,
    )

    try:
        executor.execute(spec.broker, spec.origin, spec.endpoint)
    except ExecutionPolicyLimitError as error:
        assert len(transport.calls) == policy.max_auto_pages
        assert all(
            int(call["page_size"]) == policy.default_auto_page_size
            for call in transport.calls
        )
        assert str(policy.source_path) in str(error)
    else:
        raise AssertionError("executor did not enforce max_auto_pages")
