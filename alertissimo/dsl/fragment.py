"""Contextualize continuation syntax against canonical orchestration intent."""

from __future__ import annotations

from alertissimo.orchestration.ir import WorkflowIR

from .surface import CandidateSet, SurfaceFragment, SurfaceScript


def fragment_surface_context(
    fragment: SurfaceFragment,
    base_workflow: WorkflowIR,
) -> SurfaceScript:
    """Build transient validation context without reconstructing prior DSL text."""

    if not base_workflow.steps:
        raise ValueError("cannot extend an empty WorkflowIR")
    sources = base_workflow.steps[0].sources
    origins = tuple(
        dict.fromkeys(source.origin for source in sources if source.origin is not None)
    )
    if not origins:
        raise ValueError(
            "base WorkflowIR does not expose candidate origins for DSL continuation"
        )
    brokers = {source.broker for source in sources if source.broker is not None}
    if len(brokers) > 1:
        raise ValueError(
            "base WorkflowIR has multiple candidate brokers and cannot supply one "
            "unqualified DSL continuation context"
        )
    return SurfaceScript(
        candidates=CandidateSet(
            origins=origins,
            broker=next(iter(brokers), None),
        ),
        clauses=fragment.clauses,
    )


__all__ = ["fragment_surface_context"]
