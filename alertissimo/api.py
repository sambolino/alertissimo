"""Stable high-level facade for DSL-driven Alertissimo clients.

UI and other external callers should enter the backend through this module instead
of composing parser, capability graph, planner, binder/executor, normalization,
and post-normalization semantic finalization themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from alertissimo.data_layer.execution import EndpointRegistry, RegistryEndpointExecutor
from alertissimo.data_layer.runtime.capability_graph import CapabilityGraph, build_capability_graph
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


@dataclass(frozen=True)
class DSLValidationResult:
    """Read-only DSL validation/compilation result suitable for interactive clients.

    ``is_valid`` means formal syntax parsed and ontology validation succeeded.
    ``is_runnable`` means the same surface also passed capability/lowering policy
    and produced a canonical ``SurfaceCompilation``.  Capability reports are kept
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
        return self.is_valid and self.compilation is not None and self.lowering_error is None


@dataclass(frozen=True)
class DSLExecutionResult:
    """One complete DSL turn from parsed surface to finalized semantic result."""

    source: str
    surface: SurfaceScript
    compilation: SurfaceCompilation
    staged: StagedWorkflowResult
    result: WorkflowPortfolioResult

    @property
    def workflow(self):
        return self.compilation.workflow

    @property
    def view(self) -> ResultViewSpec:
        return self.compilation.view

    @property
    def run(self) -> WorkflowRun:
        return self.result.run


def validate_dsl(
    source: str,
    *,
    graph: CapabilityGraph | None = None,
    semantic_paths: Any | None = None,
    name: str | None = None,
) -> DSLValidationResult:
    """Validate DSL without contacting provider APIs.

    The function performs formal parsing, ontology validation, capability
    validation, and canonical lowering.  Errors expected during interactive DSL
    construction are returned as data rather than raised.
    """

    try:
        surface = parse_surface_script(source)
    except DSLParseError as error:
        return DSLValidationResult(source=source, parse_error=error)

    semantic = validate_surface_semantics(surface, semantic_paths=semantic_paths)
    if not semantic.is_valid:
        return DSLValidationResult(
            source=source,
            surface=surface,
            semantic=semantic,
        )

    effective_graph = graph or build_capability_graph()
    capabilities = validate_surface_capabilities(
        surface,
        graph=effective_graph,
        semantic_paths=semantic_paths,
    )
    try:
        compilation = compile_surface(
            surface,
            graph=effective_graph,
            semantic_paths=semantic_paths,
            name=name,
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
    semantic_paths: Any | None = None,
    registry: EndpointRegistry | None = None,
    executor: EndpointExecutor | None = None,
    validate_semantic_model: bool = True,
) -> DSLExecutionResult:
    """Execute one complete DSL turn through the existing backend pipeline.

    Unlike ``validate_dsl()``, expected parse/capability/lowering/runtime failures
    are raised using the existing layer-specific exception types.  Optional graph,
    registry, and executor injection keeps the same public entry point usable by
    tests, embedded clients, and future service adapters.
    """

    effective_graph = graph or build_capability_graph()
    surface = parse_surface_script(source)
    compilation = compile_surface(
        surface,
        graph=effective_graph,
        semantic_paths=semantic_paths,
        name=name,
    )
    run = plan_workflow(compilation.workflow, effective_graph)

    effective_registry = registry or EndpointRegistry()
    effective_executor = executor or RegistryEndpointExecutor(registry=effective_registry)
    staged = execute_staged_workflow_run(
        run,
        effective_registry,
        effective_executor,
        validate_semantic_model=validate_semantic_model,
    )
    result = finalize_local_semantics(staged.normalized)

    return DSLExecutionResult(
        source=source,
        surface=surface,
        compilation=compilation,
        staged=staged,
        result=result,
    )


__all__ = [
    "DSLExecutionResult",
    "DSLValidationResult",
    "execute_dsl",
    "validate_dsl",
]
