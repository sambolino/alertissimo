"""Stable high-level facade for DSL-driven Alertissimo clients.

UI and other external callers should enter the backend through this module instead
of composing parser, capability graph, planner, binder/executor, normalization,
and post-normalization semantic finalization themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from threading import Lock
from typing import Any

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.representations import Portfolio
from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    build_capability_graph,
)
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict
from alertissimo.dsl import (
    DSLParseError,
    SurfaceCapabilityReport,
    SurfaceCompilation,
    SurfaceLoweringError,
    SurfaceScript,
    SurfaceValidationReport,
    compile_surface,
    parse_surface_script,
    validate_surface_capabilities,
    validate_surface_semantics,
)
from alertissimo.orchestration.incremental import (
    IncrementalExecutionError,
    execute_incremental_workflow_run,
)
from alertissimo.orchestration.ir import WorkflowIR
from alertissimo.orchestration.local_semantics import finalize_local_semantics
from alertissimo.orchestration.normalization import WorkflowPortfolioResult
from alertissimo.orchestration.pipeline import (
    EndpointExecutor,
    StagedWorkflowResult,
    execute_staged_workflow_run,
)
from alertissimo.orchestration.planner import plan_workflow
from alertissimo.orchestration.results import ResultViewSpec
from alertissimo.orchestration.runtime import WorkflowRun
from alertissimo.orchestration.state import (
    InMemoryWorkflowStateRepository,
    WorkflowNotFoundError,
    WorkflowSnapshot,
    WorkflowStateError,
    WorkflowStateRepository,
    WorkflowVersionConflictError,
)


@dataclass(frozen=True)
class DSLValidationResult:
    """Read-only DSL validation/compilation result suitable for interactive clients.

    ``is_valid`` means formal syntax parsed and ontology validation succeeded.
    ``is_runnable`` means the same surface also passed capability/lowering policy
    and produced a canonical ``SurfaceCompilation``. Capability reports are kept
    separately so clients may still show supported/deferred/unsupported details.
    """

    source: str
    surface: SurfaceScript | None = None
    semantic: SurfaceValidationReport | None = None
    capabilities: SurfaceCapabilityReport | None = None
    compilation: SurfaceCompilation | None = None
    parse_error: DSLParseError | None = None
    lowering_error: SurfaceLoweringError | None = None

    @property
    def is_valid(self) -> bool:
        return (
            self.parse_error is None
            and self.surface is not None
            and self.semantic is not None
            and self.semantic.is_valid
        )

    @property
    def is_runnable(self) -> bool:
        return (
            self.is_valid
            and self.compilation is not None
            and self.lowering_error is None
        )


@dataclass(frozen=True)
class DSLExecutionResult:
    """One complete DSL turn from parsed surface to finalized semantic result."""

    source: str
    surface: SurfaceScript
    compilation: SurfaceCompilation
    staged: StagedWorkflowResult
    result: WorkflowPortfolioResult

    @property
    def workflow(self) -> WorkflowIR:
        return self.compilation.workflow

    @property
    def view(self) -> ResultViewSpec:
        return self.compilation.view

    @property
    def run(self) -> WorkflowRun:
        return self.result.run

    @property
    def result_step_index(self) -> int | None:
        """Step occurrence that owns the final semantic material view."""

        return self.result.steps[-1].step_index if self.result.steps else None

    @property
    def portfolios(self) -> tuple[Portfolio, ...]:
        """Final workflow result as occurrence-owned semantic Portfolios."""

        return self.result.steps[-1].portfolios if self.result.steps else ()

    def to_dict(self) -> dict[str, Any]:
        """Return the browser-safe final semantic result plus workflow metadata.

        Portfolio payloads reuse the canonical ``portfolio_to_dict`` serializer used
        by ``.ui-fixtures`` so live execution and offline UI fixtures share exactly
        the same Portfolio/SemanticRecord wire format. Historical Step Portfolio
        snapshots remain available on the Python ``result`` object but are not
        duplicated into the primary UI payload. Raw provider payloads are not
        exported.
        """

        return {
            "source": self.source,
            "surface": self.surface.model_dump(mode="json"),
            "workflow": self.workflow.model_dump(mode="json"),
            "view": self.view.model_dump(mode="json"),
            "run": self.run.model_dump(mode="json", exclude={"workflow"}),
            "result_step_index": self.result_step_index,
            "portfolios": [
                portfolio_to_dict(portfolio) for portfolio in self.portfolios
            ],
        }

    def to_json(self, *, indent: int = 2) -> str:
        """Serialize the final DSL result as deterministic browser-friendly JSON."""

        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def _continuation_source(
    source: str,
    continue_from: DSLExecutionResult | None,
) -> str:
    """Return a complete DSL program for a fresh or incremental turn.

    Continuation is explicit caller state, not hidden facade state.  The supplied
    fragment is appended to the exact previously executed DSL program, so the
    ordinary parser/lowering/planner continue to define semantics.  A second
    ``objects from`` statement is therefore rejected by the existing grammar and
    structural validation rather than being assigned special continuation meaning.
    """

    if continue_from is None:
        return source
    fragment = source.strip()
    if not fragment:
        raise DSLParseError("DSL continuation is empty")
    return continue_from.source.rstrip() + "\n" + fragment


def _require_semantic_extension(
    previous: DSLExecutionResult,
    compilation: SurfaceCompilation,
) -> None:
    previous_steps = tuple(previous.workflow.steps)
    if tuple(compilation.workflow.steps[: len(previous_steps)]) != previous_steps:
        raise SurfaceLoweringError(
            "continuation changes previously executed semantic Steps; start a fresh "
            "DSL execution instead",
            code="continuation_changes_prior_workflow",
        )


def validate_dsl(
    source: str,
    *,
    graph: CapabilityGraph | None = None,
    name: str | None = None,
    continue_from: DSLExecutionResult | None = None,
) -> DSLValidationResult:
    """Validate DSL without contacting provider APIs.

    The function performs formal parsing, ontology validation, capability
    validation, and canonical lowering. Errors expected during interactive DSL
    construction are returned as data rather than raised.

    When ``continue_from`` is supplied, ``source`` is a clause-only continuation
    fragment. It is appended to the exact previous DSL program for validation; the
    resulting workflow must preserve the previous semantic Steps as an exact prefix.
    """

    try:
        effective_source = _continuation_source(source, continue_from)
        surface = parse_surface_script(effective_source)
    except DSLParseError as error:
        return DSLValidationResult(source=source, parse_error=error)

    semantic = validate_surface_semantics(surface)
    if not semantic.is_valid:
        return DSLValidationResult(
            source=effective_source,
            surface=surface,
            semantic=semantic,
        )

    effective_graph = graph if graph is not None else build_capability_graph()
    capabilities = validate_surface_capabilities(surface, graph=effective_graph)
    try:
        compilation = compile_surface(
            surface,
            graph=effective_graph,
            name=name,
        )
        if continue_from is not None:
            _require_semantic_extension(continue_from, compilation)
    except SurfaceLoweringError as error:
        return DSLValidationResult(
            source=effective_source,
            surface=surface,
            semantic=semantic,
            capabilities=capabilities,
            lowering_error=error,
        )

    return DSLValidationResult(
        source=effective_source,
        surface=surface,
        semantic=semantic,
        capabilities=capabilities,
        compilation=compilation,
    )


def execute_dsl(
    source: str,
    *,
    name: str | None = None,
    graph: CapabilityGraph | None = None,
    registry: EndpointRegistry | None = None,
    executor: EndpointExecutor | None = None,
    validate_semantic_model: bool = True,
    continue_from: DSLExecutionResult | None = None,
) -> DSLExecutionResult:
    """Execute a fresh DSL program or append a continuation to a prior result.

    Fresh execution follows the ordinary parser -> compiler -> planner -> staged
    runtime pipeline.  With ``continue_from``, ``source`` is appended as new DSL
    clauses to the exact prior program. The cumulative workflow is planned again,
    but the generic incremental runtime proves that the old semantic/physical plan
    remains an exact prefix and replays its existing physical executions. Only newly
    appended provider work reaches the underlying executor.

    No session state is stored inside the facade: callers explicitly retain and pass
    the prior ``DSLExecutionResult``. This keeps continuation deterministic and lets
    UI, notebook, or service clients decide how long a result remains available.
    """

    effective_graph = graph if graph is not None else build_capability_graph()
    effective_source = _continuation_source(source, continue_from)
    surface = parse_surface_script(effective_source)
    compilation = compile_surface(
        surface,
        graph=effective_graph,
        name=name,
    )
    if continue_from is not None:
        _require_semantic_extension(continue_from, compilation)
    run = plan_workflow(compilation.workflow, effective_graph)

    effective_registry = registry if registry is not None else EndpointRegistry()
    effective_executor = (
        executor
        if executor is not None
        else RegistryEndpointExecutor(registry=effective_registry)
    )
    if continue_from is None:
        staged = execute_staged_workflow_run(
            run,
            effective_registry,
            effective_executor,
            validate_semantic_model=validate_semantic_model,
        )
    else:
        staged = execute_incremental_workflow_run(
            run,
            continue_from.staged,
            effective_registry,
            effective_executor,
            validate_semantic_model=validate_semantic_model,
        )
    result = finalize_local_semantics(staged.normalized)

    return DSLExecutionResult(
        source=effective_source,
        surface=surface,
        compilation=compilation,
        staged=staged,
        result=result,
    )


class DSLWorkflowService:
    """Stateful system facade over the stateless DSL execution core.

    The service owns workflow snapshots and execution dependencies. A caller sends
    only a continuation fragment, ``workflow_id``, and ``base_version``; the prior
    ``DSLExecutionResult`` never crosses the service boundary. State remains explicit
    and addressable rather than being inferred from a global "current workflow".
    """

    def __init__(
        self,
        *,
        repository: WorkflowStateRepository[DSLExecutionResult] | None = None,
        graph: CapabilityGraph | None = None,
        registry: EndpointRegistry | None = None,
        executor: EndpointExecutor | None = None,
        validate_semantic_model: bool = True,
    ) -> None:
        self.repository = (
            repository
            if repository is not None
            else InMemoryWorkflowStateRepository()
        )
        self.graph = graph if graph is not None else build_capability_graph()
        self.registry = registry if registry is not None else EndpointRegistry()
        self.executor = (
            executor
            if executor is not None
            else RegistryEndpointExecutor(registry=self.registry)
        )
        self.validate_semantic_model = validate_semantic_model
        self._workflow_locks: dict[str, Lock] = {}
        self._workflow_locks_guard = Lock()

    def _workflow_lock(self, workflow_id: str) -> Lock:
        with self._workflow_locks_guard:
            return self._workflow_locks.setdefault(workflow_id, Lock())

    @staticmethod
    def _require_context(
        workflow_id: str | None,
        base_version: int | None,
    ) -> None:
        if workflow_id is None and base_version is not None:
            raise WorkflowStateError(
                "base_version cannot be supplied without workflow_id"
            )
        if workflow_id is not None and base_version is None:
            raise WorkflowStateError(
                "base_version is required when workflow_id is supplied"
            )

    def _load_base(
        self,
        workflow_id: str,
        base_version: int,
    ) -> WorkflowSnapshot[DSLExecutionResult]:
        previous = self.repository.latest(workflow_id)
        if previous.version != base_version:
            raise WorkflowVersionConflictError(
                f"workflow {workflow_id!r} is at version {previous.version}, "
                f"not requested base_version {base_version}"
            )
        return previous

    def validate_dsl(
        self,
        source: str,
        *,
        workflow_id: str | None = None,
        base_version: int | None = None,
        name: str | None = None,
    ) -> DSLValidationResult:
        """Validate a fresh program or a fragment against stored workflow state."""

        self._require_context(workflow_id, base_version)
        if workflow_id is None:
            return validate_dsl(source, graph=self.graph, name=name)
        assert base_version is not None
        with self._workflow_lock(workflow_id):
            previous = self._load_base(workflow_id, base_version)
            return validate_dsl(
                source,
                graph=self.graph,
                name=name,
                continue_from=previous.result,
            )

    def execute_dsl(
        self,
        source: str,
        *,
        workflow_id: str | None = None,
        base_version: int | None = None,
        name: str | None = None,
    ) -> WorkflowSnapshot[DSLExecutionResult]:
        """Execute a fresh program or continue one backend-owned workflow."""

        self._require_context(workflow_id, base_version)
        if workflow_id is None:
            execution = execute_dsl(
                source,
                name=name,
                graph=self.graph,
                registry=self.registry,
                executor=self.executor,
                validate_semantic_model=self.validate_semantic_model,
            )
            return self.repository.create(execution)

        assert base_version is not None
        with self._workflow_lock(workflow_id):
            previous = self._load_base(workflow_id, base_version)
            execution = execute_dsl(
                source,
                name=name,
                graph=self.graph,
                registry=self.registry,
                executor=self.executor,
                validate_semantic_model=self.validate_semantic_model,
                continue_from=previous.result,
            )
            return self.repository.append(
                workflow_id,
                expected_version=base_version,
                result=execution,
            )


__all__ = [
    "DSLWorkflowService",
    "DSLExecutionResult",
    "DSLValidationResult",
    "InMemoryWorkflowStateRepository",
    "IncrementalExecutionError",
    "WorkflowNotFoundError",
    "WorkflowSnapshot",
    "WorkflowStateError",
    "WorkflowStateRepository",
    "WorkflowVersionConflictError",
    "execute_dsl",
    "validate_dsl",
]
