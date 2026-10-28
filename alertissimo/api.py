"""Stable high-level facade for DSL-driven Alertissimo clients.

UI and other external callers should enter the backend through this module instead
of composing parser, capability graph, planner, binder/executor, normalization,
and post-normalization semantic finalization themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from threading import RLock
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
    SurfaceFragment,
    SurfaceLoweringError,
    SurfaceScript,
    SurfaceValidationReport,
    compile_surface,
    compile_surface_fragment,
    parse_surface_fragment,
    parse_surface_script,
    validate_surface_capabilities,
    validate_surface_fragment_capabilities,
    validate_surface_fragment_semantics,
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
from alertissimo.orchestration.planner import PlanningError, plan_workflow
from alertissimo.orchestration.results import ResultViewSpec
from alertissimo.orchestration.runtime import WorkflowRun


@dataclass(frozen=True)
class DSLValidationResult:
    """Read-only DSL validation/compilation result suitable for interactive clients.

    ``is_valid`` means formal syntax parsed and ontology validation succeeded.
    ``is_runnable`` means the same surface passed capability/lowering and offline
    planning policy and produced a canonical ``SurfaceCompilation``. Reports are kept
    separately so clients may still show supported/deferred/unsupported details.
    """

    source: str
    surface: SurfaceScript | SurfaceFragment | None = None
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
    surface: SurfaceScript | SurfaceFragment
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


# Compatibility context for single-client scripts that omit ``continue_from``.
# Interactive clients pass an explicit result (or None) stored by their session;
# those calls neither read nor replace this process-local reference.
_active_workflow: StagedWorkflowResult | None = None
_active_dsl_lock = RLock()


class _ContinuationMode(Enum):
    ACTIVE = "active"


def _is_complete_program(source: str) -> bool:
    for raw in source.splitlines():
        text = raw.strip()
        if text and not text.startswith("#"):
            head = text.lower()
            return head.startswith("objects from ") or head.split(maxsplit=1)[0] in {
                "object",
                "objects",
                "alert",
                "alerts",
            }
    return False


def _parse_dsl_turn(
    source: str,
    *,
    continue_from: DSLExecutionResult | None | _ContinuationMode = _ContinuationMode.ACTIVE,
) -> tuple[SurfaceScript | SurfaceFragment, StagedWorkflowResult | None]:
    """Parse a complete program or an IR-contextual continuation fragment."""

    if _is_complete_program(source):
        if isinstance(continue_from, DSLExecutionResult):
            raise DSLParseError(
                "an explicit continuation must contain continuation clauses only; "
                "pass continue_from=None to start a fresh workflow"
            )
        return parse_surface_script(source), None
    fragment = parse_surface_fragment(source)
    if continue_from is _ContinuationMode.ACTIVE:
        previous = _active_workflow
    elif continue_from is None:
        previous = None
    else:
        previous = continue_from.staged
    if previous is None:
        raise DSLParseError(
            "DSL continuation requires an already executed workflow; the first "
            "request must begin with a candidate search or explicit object/alert lookup"
        )
    return fragment, previous


def validate_dsl(
    source: str,
    *,
    graph: CapabilityGraph | None = None,
    name: str | None = None,
    continue_from: DSLExecutionResult | None | _ContinuationMode = _ContinuationMode.ACTIVE,
) -> DSLValidationResult:
    """Validate DSL without contacting provider APIs.

    The function performs formal parsing, ontology validation, capability
    validation, and canonical lowering. Errors expected during interactive DSL
    construction are returned as data rather than raised.

    A complete program validates independently. A clause-only fragment is compiled
    directly against the canonical WorkflowIR inside the supplied prior result.
    Explicit None requires a fresh complete program. Omitting ``continue_from``
    preserves implicit continuation for single-client scripts. Validation never
    changes either the supplied result or the compatibility context.
    """

    with _active_dsl_lock:
        try:
            surface, previous = _parse_dsl_turn(source, continue_from=continue_from)
        except DSLParseError as error:
            return DSLValidationResult(source=source, parse_error=error)

        semantic = (
            validate_surface_semantics(surface)
            if previous is None
            else validate_surface_fragment_semantics(
                surface,
                previous.run.workflow,
            )
        )
        if not semantic.is_valid:
            return DSLValidationResult(
                source=source,
                surface=surface,
                semantic=semantic,
            )

        effective_graph = graph if graph is not None else build_capability_graph()
        capabilities = (
            validate_surface_capabilities(surface, graph=effective_graph)
            if previous is None
            else validate_surface_fragment_capabilities(
                surface,
                previous.run.workflow,
                graph=effective_graph,
            )
        )
        try:
            compilation = (
                compile_surface(
                    surface,
                    graph=effective_graph,
                    name=name,
                )
                if previous is None
                else compile_surface_fragment(
                    surface,
                    previous.run.workflow,
                    graph=effective_graph,
                    name=name,
                )
            )
            # Admission uses the same offline planner as execution. Feasible
            # capabilities alone do not establish an unambiguous physical plan.
            plan_workflow(compilation.workflow, effective_graph)
        except PlanningError as error:
            return DSLValidationResult(
                source=source,
                surface=surface,
                semantic=semantic,
                capabilities=capabilities,
                lowering_error=SurfaceLoweringError(str(error), code="planning_error"),
            )
        except SurfaceLoweringError as error:
            return DSLValidationResult(
                source=source,
                surface=surface,
                semantic=semantic,
                capabilities=capabilities,
                lowering_error=error,
            )

        return DSLValidationResult(
            source=source,
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
    continue_from: DSLExecutionResult | None | _ContinuationMode = _ContinuationMode.ACTIVE,
) -> DSLExecutionResult:
    """Execute a complete DSL program or continue a prior execution result.

    A complete program starts a fresh generic workflow. A clause-only fragment is
    lowered directly onto the supplied prior WorkflowIR, then incremental execution
    replays the exact old physical prefix and executes only new provider work.
    Interactive clients pass ``continue_from=None`` for fresh work and their
    session's prior result for fragments. Explicit calls never read or update the
    implicit active workflow; omitting the argument retains script compatibility.
    """

    global _active_workflow
    with _active_dsl_lock:
        effective_graph = graph if graph is not None else build_capability_graph()
        surface, previous = _parse_dsl_turn(source, continue_from=continue_from)
        compilation = (
            compile_surface(
                surface,
                graph=effective_graph,
                name=name,
            )
            if previous is None
            else compile_surface_fragment(
                surface,
                previous.run.workflow,
                graph=effective_graph,
                name=name,
            )
        )
        run = plan_workflow(compilation.workflow, effective_graph)

        effective_registry = registry if registry is not None else EndpointRegistry()
        effective_executor = (
            executor
            if executor is not None
            else RegistryEndpointExecutor(registry=effective_registry)
        )
        if previous is None:
            staged = execute_staged_workflow_run(
                run,
                effective_registry,
                effective_executor,
                validate_semantic_model=validate_semantic_model,
            )
        else:
            staged = execute_incremental_workflow_run(
                run,
                previous,
                effective_registry,
                effective_executor,
                validate_semantic_model=validate_semantic_model,
            )
        result = finalize_local_semantics(staged.normalized)

        execution = DSLExecutionResult(
            source=source,
            surface=surface,
            compilation=compilation,
            staged=staged,
            result=result,
        )
        if continue_from is _ContinuationMode.ACTIVE:
            _active_workflow = staged
        return execution


__all__ = [
    "DSLExecutionResult",
    "DSLValidationResult",
    "IncrementalExecutionError",
    "execute_dsl",
    "validate_dsl",
]
