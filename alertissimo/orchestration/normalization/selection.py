"""Reduce a complete normalized candidate universe using canonical selection."""

from __future__ import annotations

import math
from collections.abc import Mapping

from alertissimo.orchestration.ir import SearchStep, Step
from alertissimo.orchestration.runtime.models import StepRun

from .models import StepPortfolioResult, summary_object_identity


class SearchSelectionError(ValueError):
    """A candidate has no trustworthy identity or numeric recency value."""


def apply_search_selection(step: Step, view: StepPortfolioResult) -> StepPortfolioResult:
    """Apply latest once, after residual pruning and object consolidation.

    Physical execution groups remain available for audit. The selected immutable
    material snapshot supplies downstream IDs and final semantic results. No
    per-page, per-source, or per-batch limits are imposed here.
    """
    if not isinstance(step, SearchStep) or step.selection is None:
        return view
    if step.semantic_type != "summary":
        raise SearchSelectionError("latest currently requires summary candidates")
    ranked = []
    for portfolio in view.portfolios:
        identity = summary_object_identity(portfolio)
        if identity is None:
            raise SearchSelectionError("latest candidate lacks an unambiguous summary object identity")
        origin, object_id = identity
        values = []
        for record in portfolio.records:
            if (
                not record.semantic_type.startswith(f"summary@{origin}:")
                or str(record.get("identity.object_id")) != object_id
            ):
                continue
            value = record.get("time.last_mjd")
            if value is None:
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                raise SearchSelectionError(f"latest candidate {identity!r} has a non-finite/non-numeric recency value")
            values.append(value)
        if not values:
            raise SearchSelectionError(f"latest candidate {identity!r} lacks summary.time.last_mjd")
        # Repeated provider records do not increase candidate cardinality. Keep
        # every record; choose the most recent known detection for this object.
        ranked.append((-max(values), identity, portfolio))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return StepPortfolioResult(
        step_index=view.step_index,
        executions=view.executions,
        materialized_portfolios=tuple(item[2] for item in ranked[:step.selection.latest]),
    )


class TimeSelectionError(SearchSelectionError):
    """Temporal membership lacks sufficient, source-aligned evidence."""


def validate_time_selection_payloads(step_run: StepRun, result) -> None:
    """Distinguish a present empty evidence collection from absent/bad data.

    Normal mapping paths tolerate absent branches. A completeness assertion must
    not turn that tolerance into a proven absence of detections. Inspect only the
    compiled evidence branch; do not validate unrelated optional provider fields.
    """
    from alertissimo.data_layer.runtime.payload_paths import RawFieldMissing, extract_raw_field

    def require_path(value, path):
        if path.startswith("[]."):
            if not isinstance(value, (list, tuple)):
                raise ValueError("expected a root collection")
            for item in value:
                require_path(item, path[3:])
            return
        if path == ".":
            if not isinstance(value, Mapping):
                raise ValueError("expected an object")
            return
        if path == "[]":
            collection, kind = value, (list, tuple)
        elif path.endswith(("[]", "{}")):
            collection = extract_raw_field(value, path[:-2])
            kind = (list, tuple) if path.endswith("[]") else Mapping
        else:
            raise ValueError("missing compiled evidence path")
        if not isinstance(collection, kind):
            raise ValueError("expected an evidence collection")

    indexes = step_run.execution_plan_indexes or tuple(range(len(step_run.endpoint_plans)))
    for plan in step_run.endpoint_plans:
        proof = plan.time_selection
        if proof is None:
            continue
        for index, execution in zip(indexes, result.executions):
            if index != proof.evidence_plan_index:
                continue
            try:
                require_path(execution.payload, proof.payload_path)
            except (RawFieldMissing, ValueError, TypeError) as error:
                raise TimeSelectionError(f"missing or malformed temporal evidence payload {proof.payload!r}") from error


def apply_time_selection(step: Step, step_run: StepRun, view: StepPortfolioResult) -> StepPortfolioResult:
    """Select candidates before latest, retaining every survivor's record.

    A proof names one required call and one mapped payload branch. This excludes
    other brokers, forced photometry, and non-detections without treating a
    detection record's noun alone as scientific proof. Completeness is declared
    by the provider contract and guarded by the existing executor, not inferred
    from the number of returned rows or a summary history overlap.
    """
    from alertissimo.data_layer.transforms.temporal import resolve_time_context, time_bound

    proofs = tuple((index, plan) for index, plan in enumerate(step_run.endpoint_plans) if plan.time_selection is not None)
    if not proofs:
        return view  # Existing native contracts keep their established behavior.
    context = getattr(step, "time_context", None)
    if not isinstance(step, SearchStep) or context is None:
        raise TimeSelectionError("time selection evidence requires a candidate time_context")
    try:
        resolved = resolve_time_context(context.model_dump(), step_run.time_reference)
        # Only the bound encoding is requested here; the declared mode is explicit.
        start, end = time_bound(time_context=resolved, bound="range", encoding="mjd", mode=context.mode)
    except (ValueError, TypeError, OverflowError) as error:
        raise TimeSelectionError(f"cannot resolve pinned candidate time interval: {error}") from error
    indexes = step_run.execution_plan_indexes
    if not indexes:
        if len(step_run.execution_ids) != len(step_run.endpoint_plans):
            raise TimeSelectionError("time selection needs execution-plan alignment")
        indexes = tuple(range(len(step_run.endpoint_plans)))
    executions = {execution.execution_id: execution for execution in view.executions}
    if len(indexes) != len(step_run.execution_ids) or not set(step_run.execution_ids).issubset(executions):
        raise TimeSelectionError("time selection needs aligned normalized executions")

    def ids_for_plan(index):
        return {execution_id for execution_id, owner in zip(step_run.execution_ids, indexes) if owner == index}

    # Preserve already-admitted native detection windows while providers migrate
    # individually to explicit proofs. Their whole-context bindings establish
    # that these are discovery calls, not supplementary histories.
    legacy_candidates = set()
    if context.mode == "detection":
        for index, plan in enumerate(step_run.endpoint_plans):
            if plan.time_selection is not None or not plan.required or plan.candidate_input_from_plan is not None:
                continue
            paths = tuple(path for source in (plan.parameter_sources or {}).values()
                          for path in (source.values() if isinstance(source, dict) else (source,)))
            if ("time_context",) in paths:
                legacy_candidates.update(summary_object_identity(portfolio)
                                         for execution_id in ids_for_plan(index)
                                         for portfolio in executions[execution_id].portfolios)
    scoped = []
    for owner_index, plan in proofs:
        proof = plan.time_selection
        if proof.mode != context.mode or proof.time_scale != "utc":
            raise TimeSelectionError("time selection proof conflicts with canonical intent")
        evidence_index = proof.evidence_plan_index
        if evidence_index >= len(step_run.endpoint_plans):
            raise TimeSelectionError("time selection references an unavailable evidence plan")
        evidence_plan = step_run.endpoint_plans[evidence_index]
        if not evidence_plan.required or (evidence_plan.broker, evidence_plan.origin) != (plan.broker, plan.origin):
            raise TimeSelectionError("time selection requires same-source required evidence")
        dependency = evidence_plan.candidate_input_from_plan
        if evidence_index != owner_index and (dependency is None or dependency.plan_index != owner_index):
            raise TimeSelectionError("time evidence must depend on its discovery owner")
        if proof.method == "native" and (evidence_index != owner_index or not proof.complete):
            raise TimeSelectionError("native time evidence must be a complete discovery selector")
        candidates = {
            summary_object_identity(portfolio)
            for execution_id in ids_for_plan(owner_index)
            for portfolio in executions[execution_id].portfolios
        }
        scoped.append((plan, proof, candidates, ids_for_plan(evidence_index)))
    selected = []
    for portfolio in view.portfolios:
        identity = summary_object_identity(portfolio)
        if identity is None:
            raise TimeSelectionError("time selection candidate lacks an unambiguous identity")
        outcomes = [True] if identity in legacy_candidates else []
        for plan, proof, candidates, evidence_ids in scoped:
            if identity not in candidates:
                continue
            noun = "detection" if context.mode == "detection" else "summary"
            field = "time.mjd" if context.mode == "detection" else f"time.{context.mode}_mjd"
            values, invalid = [], False
            for record in portfolio.records:
                if record.semantic_type != f"{noun}@{plan.origin}:{plan.broker}":
                    continue
                source = record.internal_source
                if source is None:
                    # Normalization may add an identity-only summary without a
                    # physical source; it says nothing about temporal evidence.
                    invalid = invalid or noun == "detection" or record.get(field) is not None
                    continue
                if source.internal_execution_id.value not in evidence_ids or source.payload_key != proof.payload:
                    continue
                value = record.get(field)
                if type(value) not in (int, float) or not math.isfinite(value):
                    invalid = True
                    continue
                values.append(value)
            if context.mode == "detection":
                if any(start <= value <= end for value in values):
                    outcomes.append(True)
                else:
                    outcomes.append(False if proof.complete and not invalid and evidence_ids else None)
            else:
                unique = set(values)
                outcomes.append(start <= values[0] <= end if len(unique) == 1 and not invalid else None)
        if True in outcomes:
            selected.append(portfolio)
        elif None in outcomes:
            raise TimeSelectionError(f"insufficient temporal evidence for candidate {identity!r}; no match is not proven")
        # An orphan supplementary row cannot create a new discovery candidate.
    return StepPortfolioResult(step_index=view.step_index, executions=view.executions,
                               materialized_portfolios=tuple(selected))
