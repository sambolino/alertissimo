"""Bridge successful orchestration results to data-layer normalization."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from alertissimo.data_layer.execution import EndpointRegistry, ExecutionResult
from alertissimo.data_layer.representations import (
    InternalEdgeId, InternalPortfolioId, InternalRecordId, Portfolio,
)
from alertissimo.data_layer.runtime.record_builder import (
    _bound_target_ids, _semantic_identifier, build_portfolios_from_execution,
)
from alertissimo.data_layer.runtime.classification_headline import (
    headline_reference, is_headline_record, materialize_headlines,
)
from alertissimo.orchestration.ir import (
    DeriveStep, FilterStep, GetClassificationStep, GetStep, LookupStep, MatchStep, SearchStep, Step, and_predicates,
)
from alertissimo.orchestration.ir.predicates import (
    Predicate, contains_collection_predicate, contains_container_reference, iter_semantic_references,
)
from alertissimo.orchestration.runtime import (
    EndpointPlan,
    EndpointPlanRef,
    StepExecutionResult,
    StepRun,
    StepRunState,
    WorkflowExecutionResult,
    WorkflowRun,
)

from .models import (
    ExecutionPortfolioResult,
    StepPortfolioResult,
    WorkflowPortfolioResult,
    consolidate_portfolios,
    summary_object_identity,
)
from .predicate import prune_portfolios
from .selection import (
    apply_deferred_search_selection, apply_search_selection, apply_time_selection,
    validate_time_selection_payloads, validate_latest_selection_payloads,
)


class WorkflowNormalizationAlignmentError(ValueError):
    """Raised before normalization when runtime results are cross-wired."""


def apply_classification_selection(step: Step, view: StepPortfolioResult) -> StepPortfolioResult:
    """Select a Get's classifier in its semantic view, keeping execution audit intact.

    Selection is restricted to records from the requested provider/survey sources.
    Raw normalization and prior Step snapshots remain immutable; a missing model
    yields no classification records for that source, rather than another model.
    """
    if isinstance(step, FilterStep):
        return view  # Filtering retains the stored interpretation of its input.
    if not isinstance(step, GetClassificationStep) or step.classifier is None:
        return StepPortfolioResult(
            step_index=view.step_index, executions=view.executions,
            materialized_portfolios=tuple(materialize_headlines(
                p, include_missing=isinstance(step, GetClassificationStep),
            ) for p in view.portfolios),
        )
    requested = _semantic_identifier(step.classifier)
    selected = []
    changed = False
    for portfolio in view.portfolios:
        executions = {item.internal_execution_id: item for item in portfolio.executions}
        removed = set()
        for record in portfolio.records:
            # A method-specific view does not claim to contain the material
            # needed to choose the default across methods.
            if is_headline_record(record):
                if not step.sources or any(
                    source.broker in (None, record.get("best.broker"))
                    and source.origin in (None, record.get("best.survey")) for source in step.sources
                ):
                    removed.add(record.internal_record_id)
                continue
            noun, _, qualifiers = record.semantic_type.partition("@")
            if noun != "classification" or record.internal_source is None:
                continue
            execution = executions.get(record.internal_source.internal_execution_id)
            if execution is None or step.sources and not any(
                (source.broker is None or source.broker == execution.broker)
                and (source.origin is None or source.origin == execution.origin)
                for source in step.sources
            ):
                continue
            producer = qualifiers.partition(":")[0]
            if producer != requested:
                removed.add(record.internal_record_id)
        if not removed:
            selected.append(portfolio)
            continue
        changed = True
        identifier = InternalPortfolioId(f"portfolio:{uuid4()}")
        edges = []
        for edge in portfolio.edges:
            if any(isinstance(value, InternalRecordId) and value in removed for value in (edge.subject, edge.target)):
                continue
            if portfolio.internal_portfolio_id in (edge.subject, edge.target):
                edge = replace(
                    edge, internal_edge_id=InternalEdgeId(f"edge:{uuid4()}"),
                    subject=identifier if edge.subject == portfolio.internal_portfolio_id else edge.subject,
                    target=identifier if edge.target == portfolio.internal_portfolio_id else edge.target,
                )
            edges.append(edge)
        selected.append(replace(
            portfolio, internal_portfolio_id=identifier,
            records=tuple(record for record in portfolio.records if record.internal_record_id not in removed),
            edges=tuple(edges),
        ))
    if not changed:
        return view
    return StepPortfolioResult(
        step_index=view.step_index, executions=view.executions,
        materialized_portfolios=tuple(selected),
    )


def normalize_execution(
    execution: ExecutionResult,
    *,
    validate_semantic_model: bool = True,
) -> tuple[Portfolio, ...]:
    """Normalize exactly one physical result using the authoritative builder.

    Validation defaults on because orchestration is a production boundary from
    physical provider data into the canonical semantic model. This helper has no
    orchestration plan context, so it deliberately performs no residual pruning.
    """

    return build_portfolios_from_execution(
        execution, validate_semantic_model=validate_semantic_model
    )


def normalize_step_execution(
    result: StepExecutionResult,
    *,
    validate_semantic_model: bool = True,
) -> StepPortfolioResult:
    """Normalize a completed Step result without endpoint-plan strategy context.

    This standalone helper remains a pure normalization bridge. Workflow-level
    normalization has the aligned EndpointPlans needed to apply residual semantic
    predicates safely.
    """

    return StepPortfolioResult(
        step_index=result.step_index,
        executions=tuple(
            ExecutionPortfolioResult(
                execution_id=execution.internal_execution_id.value,
                portfolios=normalize_execution(
                    execution,
                    validate_semantic_model=validate_semantic_model,
                ),
            )
            for execution in result.executions
        ),
    )


def _plan_at(run: WorkflowRun, reference: EndpointPlanRef) -> EndpointPlan:
    try:
        step_run = run.steps[reference.step_index]
        return step_run.endpoint_plans[reference.plan_index]
    except IndexError as error:
        raise WorkflowNormalizationAlignmentError(
            "execution reuse references an unavailable endpoint plan "
            f"({reference.step_index}, {reference.plan_index})"
        ) from error


def _execution_plan_indexes(
    step_run: StepRun, step_result: StepExecutionResult
) -> tuple[int, ...]:
    """Return endpoint-plan indexes corresponding to successful executions.

    Older/dense results may omit explicit index metadata; equal plan/result counts
    retain their historical positional meaning. Sparse results must provide the
    explicit indexes recorded by runtime execution.
    """

    if step_run.execution_plan_indexes:
        if len(step_run.execution_plan_indexes) != len(step_result.executions):
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} execution-plan index count does "
                "not match execution result count"
            )
        return step_run.execution_plan_indexes
    if len(step_run.endpoint_plans) == len(step_result.executions):
        return tuple(range(len(step_result.executions)))
    if not step_result.executions:
        return ()
    raise WorkflowNormalizationAlignmentError(
        f"step_index {step_run.step_index} has sparse execution results without "
        "execution-plan index metadata"
    )


def _effective_residual(
    run: WorkflowRun,
    step_index: int,
    plan_index: int,
    *,
    visited: frozenset[tuple[int, int]] = frozenset(),
) -> Predicate | None:
    """Combine residuals inherited through execution reuse with this plan's own."""

    key = (step_index, plan_index)
    if key in visited:
        raise WorkflowNormalizationAlignmentError(
            f"execution reuse cycle detected at endpoint plan {key}"
        )
    plan = run.steps[step_index].endpoint_plans[plan_index]
    own = (
        plan.predicate_realization.residual
        if plan.predicate_realization is not None
        else None
    )
    reference = plan.execution_reuse_from
    if reference is None:
        return own
    inherited = _effective_residual(
        run,
        reference.step_index,
        reference.plan_index,
        visited=visited | {key},
    )
    return and_predicates(
        predicate for predicate in (inherited, own) if predicate is not None
    )


def _normalize_planned_execution(
    execution: ExecutionResult,
    residual: Predicate | None,
    normalized_by_execution_id: dict[str, tuple[Portfolio, ...]],
    *,
    validate_semantic_model: bool,
    diagnostics: list[str] | None = None,
) -> ExecutionPortfolioResult:
    """Reuse base normalization for one physical execution, then apply a Step view.

    Coalesced semantic Steps carry the same physical execution ID. Normalizing that
    execution repeatedly would manufacture distinct Portfolio identities for the
    same physical result. The cache therefore owns the base normalized Portfolios;
    residual pruning only selects from that shared tuple and never clones them.
    """

    execution_id = execution.internal_execution_id.value
    portfolios = normalized_by_execution_id.get(execution_id)
    if portfolios is None:
        portfolios = normalize_execution(
            execution,
            validate_semantic_model=validate_semantic_model,
        )
        normalized_by_execution_id[execution_id] = portfolios
    if residual is not None:
        portfolios = prune_portfolios(portfolios, residual, diagnostics=diagnostics)
    return ExecutionPortfolioResult(
        execution_id=execution_id,
        portfolios=portfolios,
    )


def _normalize_planned_step(
    result: StepExecutionResult,
    step_run: StepRun,
    run: WorkflowRun,
    normalized_by_execution_id: dict[str, tuple[Portfolio, ...]],
    *,
    validate_semantic_model: bool,
    diagnostics: list[str] | None = None,
) -> StepPortfolioResult:
    """Normalize successful executions against their owning endpoint plans."""

    plan_indexes = _execution_plan_indexes(step_run, result)
    validate_time_selection_payloads(step_run, result)
    validate_latest_selection_payloads(step_run, result)
    return StepPortfolioResult(
        step_index=result.step_index,
        executions=tuple(
            _normalize_planned_execution(
                execution,
                _effective_residual(
                    run,
                    step_run.step_index,
                    plan_index,
                ),
                normalized_by_execution_id,
                validate_semantic_model=validate_semantic_model, diagnostics=diagnostics,
            )
            for plan_index, execution in zip(plan_indexes, result.executions)
        ),
    )


def _materialize_enrichment_view(
    step_run: StepRun,
    own: StepPortfolioResult,
    normalized_steps: list[StepPortfolioResult],
) -> StepPortfolioResult:
    """Combine inherited semantic material with this Step's newly normalized data.

    ``material_input_from`` is the semantic view this targetless provider enrichment
    extends. Physical EndpointPlan candidate references remain a separate concern
    and continue to determine which object IDs are sent to provider calls. Historical
    source Steps are never mutated.
    """

    reference = step_run.material_input_from
    if reference is None:
        return own
    try:
        source = normalized_steps[reference.step_index]
    except IndexError as error:
        raise WorkflowNormalizationAlignmentError(
            f"provider step_index {step_run.step_index} references unavailable "
            f"material Step {reference.step_index}"
        ) from error
    if reference.step_index >= step_run.step_index:
        raise WorkflowNormalizationAlignmentError(
            f"provider step_index {step_run.step_index} material input must reference "
            "an earlier Step"
        )
    # Enrichment extends the selected population, whether calls are fresh or reused.
    # Keep the unscoped physical response in executions for audit purposes.
    survivors = {summary_object_identity(portfolio) for portfolio in source.portfolios} - {None}
    incoming = tuple(portfolio for portfolio in own.portfolios
                     if summary_object_identity(portfolio) in survivors)
    return StepPortfolioResult(
        step_index=own.step_index,
        executions=own.executions,
        materialized_portfolios=consolidate_portfolios(source.portfolios + incoming),
    )


def filter_execution_groups(source, predicate, materialized):
    """Project material selection back onto physical audit groups.

    Collections and composed headlines belong to the material view. Re-evaluating
    either on a partial physical response would make a second, different decision.
    Existing scalar predicates retain their execution-local projection.
    """
    normalized = contains_collection_predicate(predicate) or contains_container_reference(predicate) or any(
        headline_reference(ref) for ref in iter_semantic_references(predicate))
    survivors = {summary_object_identity(p) for p in materialized} - {None}
    surviving_ids = {p.internal_portfolio_id for p in materialized}
    return tuple(
        ExecutionPortfolioResult(
            execution_id=execution.execution_id,
            portfolios=(tuple(p for p in execution.portfolios
                              if summary_object_identity(p) in survivors
                              or p.internal_portfolio_id in surviving_ids)
                        if normalized else prune_portfolios(execution.portfolios, predicate)),
        )
        for execution in source.executions
    )


def _materialized_raw_field(value, path):
    """Inspect receipt data without invoking a deferred client relationship."""
    from collections.abc import Mapping
    from alertissimo.data_layer.runtime.payload_paths import RawFieldMissing

    for key in path.split("."):
        if isinstance(value, Mapping):
            if key not in value:
                raise RawFieldMissing(path)
            value = value[key]
        elif isinstance(value, (list, tuple)) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            try:
                attributes = vars(value)
            except TypeError as error:
                raise RawFieldMissing(path) from error
            if key not in attributes:
                raise RawFieldMissing(path)
            value = attributes[key]
    return value


def _component_empty_evidence(run, results, portfolios, before_step, graph, registry):
    """Reconstruct empty receipts, never completeness of a nonempty history.

    Keys reuse transient collection evidence: (Portfolio ID, qualified array).
    Nothing is persisted, and no empty observation/product record is fabricated.
    Missing/null/malformed arrays and rows omitted by normalization are not empty.
    """
    from alertissimo.data_layer.runtime.payload_paths import RawFieldMissing
    from alertissimo.orchestration.ir.predicates import _collection_paths
    from alertissimo.orchestration.validation import component_output_matches
    if graph is None:
        return {}
    model = _collection_paths()
    def product_key(field):
        product = field.semantic_record_type
        return product + ":" + field.broker if "@" in product and ":" not in product else product
    evidence = {}
    start = 0
    for index, step in enumerate(run.workflow.steps[:before_step]):
        if isinstance(step, (SearchStep, LookupStep)) or isinstance(step, GetStep) and step.target is not None:
            start = index
    for index in range(start, min(before_step, len(results))):
        step = run.workflow.steps[index]
        if not isinstance(step, GetStep) or not step.required_components:
            continue
        step_run = run.steps[index]
        if step_run.state is not StepRunState.SUCCEEDED:
            continue
        execution_result = results[index]
        indexes = _execution_plan_indexes(step_run, execution_result)
        for component in step.required_components:
            boundaries = model.array_boundaries(component.ontology_path)
            if not boundaries:
                continue
            array = component.model_copy(update={"field_path": boundaries[-1].partition(".")[2]})
            owners = []
            for plan_index, plan in enumerate(step_run.endpoint_plans):
                fields = tuple(f for f in graph.fields_for_endpoint(plan.broker, plan.origin, plan.endpoint)
                               if component_output_matches(step, f, array))
                if fields:
                    owners.append((plan_index, plan, fields))
            if not owners or any(not plan.required for _, plan, _ in owners):
                continue
            for portfolio in portfolios:
                identity = summary_object_identity(portfolio)
                if identity is None:
                    continue
                origin, object_id = identity
                relevant = tuple(owner for owner in owners if owner[1].origin == origin)
                if not relevant:
                    continue
                for _, _, fields in relevant:
                    for field in fields:
                        evidence.pop((portfolio.internal_portfolio_id.value,
                                      product_key(field) + "." + array.field_path), None)
                products = set()
                established = True
                for plan_index, plan, fields in relevant:
                    covered = False
                    for owner, execution in zip(indexes, execution_result.executions):
                        if owner != plan_index:
                            continue
                        targets = tuple(str(value) for value in _bound_target_ids(execution, providers_root=registry.root))
                        if object_id not in targets:
                            continue
                        paths = {field.payload_path for field in fields}
                        # Only a wholly empty returned collection, or an explicit
                        # empty collection in its identity-bound parent, proves this.
                        empty = True
                        for path in paths:
                            if path == "[]":
                                value = execution.payload
                            elif path.startswith("[].") and path.endswith("[]"):
                                # An empty child must belong to this object, not
                                # another root in the same batched response.
                                keys = {field.payload_key for field in fields if field.payload_path == path}
                                definitions = tuple(p for p in graph.payload_capabilities
                                    if (p.broker, p.origin, p.endpoint) == (plan.broker, plan.origin, plan.endpoint)
                                    and p.payload_key in keys)
                                if (not isinstance(execution.payload, (list, tuple))
                                    or {p.payload_key for p in definitions} != keys
                                    or any(p.partition_mode != "root_field" or not p.partition_field for p in definitions)):
                                    empty = False
                                    break
                                try:
                                    identified = tuple((row, tuple(_materialized_raw_field(row, p.partition_field)
                                                       for p in definitions)) for row in execution.payload)
                                    if any(not isinstance(value, (str, int)) or isinstance(value, bool)
                                           for _, values in identified for value in values):
                                        empty = False
                                        break
                                    parents = tuple(row for row, values in identified
                                                    if all(str(value) == object_id for value in values))
                                    if len(parents) != 1:
                                        empty = False
                                        break
                                    value = _materialized_raw_field(parents[0], path[3:-2])
                                except RawFieldMissing:
                                    empty = False
                                    break
                            elif len(targets) == 1 and path.endswith("[]") and not path.startswith("[]."):
                                try:
                                    value = _materialized_raw_field(execution.payload, path[:-2])
                                except RawFieldMissing:
                                    empty = False
                                    break
                            else:
                                empty = False
                                break
                            if not isinstance(value, (tuple, list)) or value:
                                empty = False
                                break
                        if not empty:
                            established = False
                            break
                        covered = True
                        products.update(product_key(f) for f in fields)
                    if not covered:
                        established = False
                    if not established:
                        break
                if established:
                    for product in products:
                        evidence[(portfolio.internal_portfolio_id.value, product + "." + array.field_path)] = (True, frozenset())
    return evidence


def _detection_collection_evidence(run, results, portfolios, before_step, graph, registry, normalized_cache):
    """Audit detection rows against their existing normalized occurrence.

    The provider's material detection proof belongs to an exact endpoint/payload.
    It can cover the same required identity-bound history acquisition without a
    temporal query. Delivery alone, summaries and response lengths cannot close it.
    Single-object and declared root-field partitions retain raw row indices.
    Mixed limit rows are checked but never broaden the proof beyond detections.
    Proof inspection reads materialized fields only, without invoking lazy getters.
    """
    from collections import Counter
    from collections.abc import Mapping
    import math
    from alertissimo.data_layer.runtime.payload_paths import RawFieldMissing
    from alertissimo.orchestration.ir.predicates import _collection_paths

    evidence = {}
    if graph is None:
        return evidence
    active = {record.internal_record_id.value for portfolio in portfolios for record in portfolio.records}
    populations = {summary_object_identity(p) for p in portfolios} - {None}
    declarations = tuple((recipe, recipe.time_selection) for recipe in graph.recipe_capabilities
                         if recipe.time_selection is not None
                         and recipe.time_selection.mode == "detection"
                         and recipe.time_selection.method == "material"
                         and recipe.time_selection.complete and recipe.time_selection.time_scale == "utc")

    def signature(fields):
        flags = tuple((key.split(".")[1], value) for key, value in fields.items()
                      if key.startswith("photometry.") and key.endswith(".upper_limit") and len(key.split(".")) == 3)
        time = fields.get("time.mjd")
        if (len(flags) != 1 or type(flags[0][1]) is not bool
            or type(time) not in (int, float) or not math.isfinite(time)):
            return None
        return time, flags[0][0], flags[0][1]

    for index, result in enumerate(results[:before_step]):
        step_run = run.steps[index]
        if step_run.state is not StepRunState.SUCCEEDED:
            continue
        indexes = _execution_plan_indexes(step_run, result)
        for owner, execution in zip(indexes, result.executions):
            plan = step_run.endpoint_plans[owner]
            if not plan.required:
                continue
            endpoint = next(e for e in graph.endpoint_capabilities
                            if (e.broker, e.origin, e.endpoint) == (plan.broker, plan.origin, plan.endpoint))
            if endpoint.supports_projection:
                continue
            targets = tuple(str(value) for value in _bound_target_ids(execution, providers_root=registry.root))
            if not targets:
                continue
            for recipe, proof in declarations:
                call = recipe.calls[proof.call_index]
                if (recipe.broker, recipe.origin, call.endpoint) != (plan.broker, plan.origin, plan.endpoint):
                    continue
                definition = next((p for p in graph.payload_capabilities
                                   if (p.broker, p.origin, p.endpoint, p.payload_key)
                                   == (plan.broker, plan.origin, plan.endpoint, proof.payload)), None)
                if definition is None or not definition.path.endswith("[]"):
                    continue
                try:
                    if definition.partition_mode == "single" and len(targets) == 1:
                        parents = ((targets[0], execution.payload),)
                        child_path = definition.path[:-2]
                    elif (definition.partition_mode == "root_field" and definition.partition_field
                          and definition.path.startswith("[].")
                          and isinstance(execution.payload, (list, tuple))):
                        identified = tuple((_materialized_raw_field(parent, definition.partition_field), parent)
                                           for parent in execution.payload)
                        if any(not isinstance(oid, (str, int)) or isinstance(oid, bool) or str(oid) == ""
                               for oid, _ in identified):
                            continue
                        parents = tuple((str(oid), parent) for oid, parent in identified)
                        if len({oid for oid, _ in parents}) != len(parents) or {oid for oid, _ in parents} != set(targets):
                            continue
                        child_path = definition.path[3:-2]
                    else:
                        continue
                    raw_by_id = {}
                    offset = 0
                    for oid, parent in parents:
                        raw = _materialized_raw_field(parent, child_path)
                        if (not isinstance(raw, (list, tuple))
                            or any(not isinstance(row, Mapping) and not hasattr(row, "__dict__") for row in raw)):
                            raise RawFieldMissing(child_path)
                        raw_by_id[oid] = (raw, list(range(offset, offset + len(raw))))
                        offset += len(raw)
                except RawFieldMissing:
                    continue
                # Empty histories normalize to no product record. Preserve a
                # scoped receipt on the existing candidate, without fabricating one.
                for object_id, (raw, _) in raw_by_id.items():
                    if raw:
                        continue
                    for portfolio in portfolios:
                        if summary_object_identity(portfolio) == (plan.origin, object_id):
                            for collection, bands in call.delivered_bands:
                                evidence[(portfolio.internal_portfolio_id.value, collection, "detections")] = (
                                    True, frozenset(bands),
                                )
                for portfolio in normalized_cache.get(execution.internal_execution_id.value, ()):
                    identity = summary_object_identity(portfolio)
                    if identity not in populations or identity[0] != plan.origin or identity[1] not in raw_by_id:
                        continue
                    object_id = identity[1]
                    raw, row_indexes = raw_by_id[object_id]
                    measurements = tuple(record for record in portfolio.records
                        if record.semantic_type == f"measurement@{plan.origin}:{plan.broker}"
                        and record.internal_source is not None
                        and record.internal_source.internal_execution_id == execution.internal_execution_id
                        and record.internal_source.payload_key == proof.payload)
                    if (len(measurements) != len(raw)
                        or sorted(r.internal_source.payload_index for r in measurements
                                  if r.internal_source.payload_index is not None) != row_indexes):
                        continue
                    if any(record.get("identity.object_id") is not None
                           and str(record.get("identity.object_id")) != object_id for record in measurements):
                        continue
                    expected = tuple(signature(record.fields) for record in measurements)
                    if any(item is None for item in expected):
                        continue
                    for collection, bands in call.delivered_bands:
                        product, _, path = collection.partition(".")
                        domain = _collection_paths().parameter_domain(collection + ".photometry.{filter}", plan.origin)
                        if domain is None or any(item[1] not in domain for item in expected):
                            continue
                        mapped = tuple(field for field in call.outputs if field.payload_key == proof.payload
                                       and field.semantic_path.startswith(collection + "."))
                        # Compare every declared point field, not just row counts
                        # or times: equal-time duplicates must not hide a lost row.
                        if not mapped or any(not any(
                            other.semantic_record_type == f"measurement@{plan.origin}:{plan.broker}"
                            and other.relative_field_path == field.relative_field_path[len(path) + 1:]
                            and other.raw_ref == field.raw_ref for other in call.outputs) for field in mapped):
                            continue
                        relative = {field.relative_field_path[len(path) + 1:] for field in mapped
                                    if not field.relative_field_path.endswith("{filter}")}

                        def projected(fields, band):
                            paths = {field.replace("{filter}", band) for field in relative}
                            return tuple(sorted((key, value) for key, value in fields.items() if key in paths))

                        records = tuple(r for r in portfolio.records if r.semantic_type == product and path in r.fields)
                        if len(records) != 1:
                            continue
                        record = records[0]
                        if record.internal_record_id.value not in active:
                            continue
                        points = record.fields[path]
                        if not isinstance(points, (tuple, list)) or any(not isinstance(p, Mapping) for p in points):
                            continue
                        actual = tuple(signature(point) for point in points)
                        if any(item is None or item[1] not in domain for item in actual):
                            continue
                        if Counter(item for item in actual if item[2] is False) != Counter(item for item in expected if item[2] is False):
                            continue
                        try:
                            expected_fields = Counter(projected(record.fields, item[1])
                                                      for record, item in zip(measurements, expected) if item[2] is False)
                            actual_fields = Counter(projected(point, item[1])
                                                    for point, item in zip(points, actual) if item[2] is False)
                        except TypeError:
                            continue  # Opaque/nonscalar mapped values cannot prove row equivalence.
                        if actual_fields != expected_fields:
                            continue
                        evidence[(record.internal_record_id.value, path, "detections")] = (True, frozenset(bands))
    return evidence


def _filter_candidate_view(
    step: FilterStep,
    step_run: StepRun,
    normalized_steps: list[StepPortfolioResult],
    *, diagnostics: list[str] | None = None,
    collection_evidence=None,
) -> StepPortfolioResult:
    """Apply one local FilterStep to an earlier normalized semantic view.

    ``executions`` retains the historical execution grouping behavior for backward
    compatibility. ``materialized_portfolios`` is authoritative when the source is
    an accumulated semantic snapshot, so filtering never discards inherited evidence
    needed by later local or provider Steps.
    """

    reference = step_run.candidate_input_from
    if reference is None:
        raise WorkflowNormalizationAlignmentError(
            f"filter step_index {step_run.step_index} has no candidate input reference"
        )
    try:
        source = normalized_steps[reference.step_index]
    except IndexError as error:
        raise WorkflowNormalizationAlignmentError(
            f"filter step_index {step_run.step_index} references unavailable "
            f"candidate Step {reference.step_index}"
        ) from error

    if step.predicate is None:
        if step.criteria:
            raise WorkflowNormalizationAlignmentError(
                "legacy FilterStep criteria have no defined local predicate evaluator"
            )
        executions = source.executions
        materialized = source.portfolios
    else:
        materialized = prune_portfolios(source.portfolios, step.predicate, diagnostics=diagnostics,
                                       collection_evidence=collection_evidence)
        executions = filter_execution_groups(source, step.predicate, materialized)
    return StepPortfolioResult(
        step_index=step_run.step_index,
        executions=executions,
        materialized_portfolios=materialized,
    )


def _executions_for_plan(
    step_run: StepRun,
    step_result: StepExecutionResult,
    plan_index: int,
) -> tuple[ExecutionResult, ...]:
    plan_indexes = _execution_plan_indexes(step_run, step_result)
    executions = tuple(execution for owner, execution in zip(plan_indexes, step_result.executions)
                       if owner == plan_index)
    if not executions:
        raise WorkflowNormalizationAlignmentError(
            "execution reuse references an endpoint plan with no successful execution "
            f"({step_run.step_index}, {plan_index})"
        )
    return executions


def _validate_reuse_alignment(
    result: WorkflowExecutionResult,
    *,
    step_index: int,
    plan_index: int,
    plan: EndpointPlan,
) -> None:
    reference = plan.execution_reuse_from
    if reference is None:
        return
    if reference.step_index >= step_index:
        raise WorkflowNormalizationAlignmentError(
            f"step_index {step_index} plan {plan_index} reuses a non-earlier Step"
        )
    owner_plan = _plan_at(result.run, reference)
    owner_step_run = result.run.steps[reference.step_index]
    owner_step_result = result.steps[reference.step_index]
    owner_executions = _executions_for_plan(
        owner_step_run, owner_step_result, reference.plan_index
    )
    consumer_executions = _executions_for_plan(
        result.run.steps[step_index], result.steps[step_index], plan_index,
    )

    if (
        owner_plan.broker,
        owner_plan.origin,
        owner_plan.endpoint,
    ) != (
        plan.broker,
        plan.origin,
        plan.endpoint,
    ):
        raise WorkflowNormalizationAlignmentError(
            "reused endpoint plan does not match owner endpoint identity"
        )
    if (
        tuple(item.internal_execution_id.value for item in owner_executions)
        != tuple(item.internal_execution_id.value for item in consumer_executions)
    ):
        raise WorkflowNormalizationAlignmentError(
            f"step_index {step_index} plan {plan_index} does not carry the "
            "ordered execution IDs of its declared reuse owner"
        )


def _validate_workflow_alignment(result: WorkflowExecutionResult) -> None:
    run = result.run
    if len(result.steps) != len(run.steps):
        raise WorkflowNormalizationAlignmentError(
            "execution Step result count does not match WorkflowRun StepRun count "
            f"({len(result.steps)} != {len(run.steps)})"
        )

    for position, (step_run, step_result) in enumerate(zip(run.steps, result.steps)):
        if step_result.step_index != step_run.step_index:
            raise WorkflowNormalizationAlignmentError(
                f"execution Step result at position {position} has step_index "
                f"{step_result.step_index}; expected {step_run.step_index}"
            )

        step = run.step_at(step_run.step_index)
        if isinstance(step, DeriveStep):
            if step_run.state is not StepRunState.PLANNED:
                raise WorkflowNormalizationAlignmentError(
                    f"derive step_index {step_run.step_index} is {step_run.state.value}; "
                    "it must remain planned until post-normalization derivation"
                )
            reference = step_run.material_input_from
            if reference is None or reference.step_index >= step_run.step_index:
                raise WorkflowNormalizationAlignmentError(
                    f"derive step_index {step_run.step_index} must reference an earlier "
                    "material Step"
                )
            if (
                step_run.endpoint_plans
                or step_run.candidate_input_from is not None
                or step_run.execution_ids
                or step_run.execution_plan_indexes
                or step_run.vacuous_plan_indexes
                or step_result.executions
            ):
                raise WorkflowNormalizationAlignmentError(
                    f"derive step_index {step_run.step_index} must have one earlier "
                    "material input but no physical endpoint plans, candidate input, "
                    "execution IDs, execution-plan indexes, vacuous-plan indexes, or "
                    "execution results"
                )
            continue

        if isinstance(step, MatchStep):
            if step_run.state is not StepRunState.PLANNED:
                raise WorkflowNormalizationAlignmentError(
                    f"match step_index {step_run.step_index} is {step_run.state.value}; "
                    "it must remain planned until post-normalization matching"
                )
            reference = step_run.candidate_input_from
            if reference is None or reference.step_index >= step_run.step_index:
                raise WorkflowNormalizationAlignmentError(
                    f"match step_index {step_run.step_index} must reference an earlier "
                    "candidate/material Step"
                )
            if (
                step_run.material_input_from is not None
                or step_run.endpoint_plans
                or step_run.execution_ids
                or step_run.execution_plan_indexes
                or step_run.vacuous_plan_indexes
                or step_result.executions
            ):
                raise WorkflowNormalizationAlignmentError(
                    f"match step_index {step_run.step_index} must have no material "
                    "input, physical endpoint plans, execution IDs, execution-plan "
                    "indexes, vacuous-plan indexes, or execution results"
                )
            continue

        if isinstance(step, FilterStep):
            if step_run.state is not StepRunState.SUCCEEDED:
                raise WorkflowNormalizationAlignmentError(
                    f"filter step_index {step_run.step_index} is {step_run.state.value}; "
                    "it must be succeeded before workflow normalization"
                )
            if step_run.candidate_input_from is None:
                raise WorkflowNormalizationAlignmentError(
                    f"filter step_index {step_run.step_index} has no candidate input"
                )
            if (
                step_run.material_input_from is not None
                or step_run.endpoint_plans
                or step_run.execution_ids
                or step_run.execution_plan_indexes
                or step_run.vacuous_plan_indexes
                or step_result.executions
            ):
                raise WorkflowNormalizationAlignmentError(
                    f"filter step_index {step_run.step_index} must have no material "
                    "input, physical endpoint plans, execution IDs, execution-plan "
                    "indexes, vacuous-plan indexes, or execution results"
                )
            continue

        if step_run.candidate_input_from is not None:
            raise WorkflowNormalizationAlignmentError(
                f"provider step_index {step_run.step_index} must not carry a StepRun "
                "candidate input; candidate IDs belong on EndpointPlans"
            )
        if step_run.material_input_from is not None:
            reference = step_run.material_input_from
            if reference.step_index >= step_run.step_index:
                raise WorkflowNormalizationAlignmentError(
                    f"provider step_index {step_run.step_index} material input must "
                    "reference an earlier Step"
                )
        if step_run.state is not StepRunState.SUCCEEDED:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} is {step_run.state.value}; "
                "workflow normalization requires succeeded state"
            )

        if (
            not step_run.execution_plan_indexes
            and step_result.executions
            and len(step_run.endpoint_plans) != len(step_result.executions)
        ):
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} endpoint plan count does not "
                "match execution result count "
                f"({len(step_run.endpoint_plans)} != {len(step_result.executions)})"
            )

        plan_indexes = _execution_plan_indexes(step_run, step_result)
        invalid_vacuous = tuple(
            index
            for index in step_run.vacuous_plan_indexes
            if index < 0 or index >= len(step_run.endpoint_plans)
        )
        if invalid_vacuous:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} vacuous endpoint plan indexes "
                f"reference unknown plans {invalid_vacuous}"
            )
        non_candidate_vacuous = tuple(
            index
            for index in step_run.vacuous_plan_indexes
            if step_run.endpoint_plans[index].candidate_input_from is None
            and step_run.endpoint_plans[index].candidate_input_from_plan is None
        )
        if non_candidate_vacuous:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} vacuous endpoint plan indexes "
                f"must be candidate-dependent {non_candidate_vacuous}"
            )

        overlap = tuple(
            sorted(set(plan_indexes) & set(step_run.vacuous_plan_indexes))
        )
        if overlap:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} endpoint plan indexes {overlap} "
                "cannot be both executed and vacuous"
            )

        missing_plan_indexes = set(range(len(step_run.endpoint_plans))) - set(plan_indexes)
        missing_required = tuple(
            index
            for index in sorted(missing_plan_indexes)
            if step_run.endpoint_plans[index].required
            and index not in step_run.vacuous_plan_indexes
        )
        if missing_required:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} is missing successful execution "
                f"results for required endpoint plan indexes {missing_required}"
            )

        validated_reuse = set()
        for execution_position, (plan_index, execution) in enumerate(
            zip(plan_indexes, step_result.executions)
        ):
            plan = step_run.endpoint_plans[plan_index]
            provenance = execution.execution_provenance
            planned_identity = (plan.broker, plan.origin, plan.endpoint)
            actual_identity = (
                provenance.broker,
                provenance.origin,
                provenance.endpoint,
            )
            if planned_identity != actual_identity:
                raise WorkflowNormalizationAlignmentError(
                    f"step_index {step_run.step_index} execution position "
                    f"{execution_position} endpoint identity does not align: "
                    f"planned broker={plan.broker}, origin={plan.origin}, "
                    f"endpoint={plan.endpoint}; actual broker={provenance.broker}, "
                    f"origin={provenance.origin}, endpoint={provenance.endpoint}"
                )
            if plan_index not in validated_reuse:
                _validate_reuse_alignment(
                    result,
                    step_index=step_run.step_index,
                    plan_index=plan_index,
                    plan=plan,
                )
                validated_reuse.add(plan_index)
        actual_ids = tuple(
            execution.internal_execution_id.value
            for execution in step_result.executions
        )
        if actual_ids != step_run.execution_ids:
            raise WorkflowNormalizationAlignmentError(
                f"step_index {step_run.step_index} execution IDs do not align in "
                f"order (StepRun has {step_run.execution_ids}, results have {actual_ids})"
            )


def normalize_workflow_execution(
    result: WorkflowExecutionResult,
    *,
    validate_semantic_model: bool = True,
    normalized_execution_cache: dict[str, tuple[Portfolio, ...]] | None = None,
    preserved_steps: tuple[StepPortfolioResult, ...] = (),
    graph=None,
    registry=None,
) -> WorkflowPortfolioResult:
    """Normalize physical executions once, then expose Step-specific semantic views.

    A reused execution inherits the residual predicate of its physical owner, so a
    later semantic enrichment cannot resurrect candidates already pruned from the
    candidate-search result. Targetless provider enrichment keeps its own physical
    executions occurrence-local while materializing an immutable semantic snapshot
    that combines the preceding material view with newly normalized evidence.
    FilterSteps select from an earlier normalized Step view without manufacturing
    physical provenance. DeriveStep and MatchStep occurrences retain empty normalized
    outputs until the ordered local semantic phase runs; Derive's planned material
    reference already records which immutable earlier snapshot it will transform.
    Supplementary physical plans that failed remain visible as runtime warnings;
    candidate-dependent vacuous plans remain proven by runtime metadata.

    ``normalized_execution_cache`` may carry base, unpruned normalization already
    produced earlier in the same staged workflow invocation. Reusing that tuple is
    essential for one-shot provider iterators and also preserves stable internal
    Portfolio identities. Residual predicates remain Step-specific views and are
    never stored back as the base normalization.
    """

    _validate_workflow_alignment(result)
    if any((isinstance(step, GetStep) and step.required_components)
           or contains_collection_predicate(getattr(step, "predicate", None)) for step in result.run.workflow.steps):
        registry = registry or EndpointRegistry()
        if graph is None:
            from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
            graph = build_capability_graph(registry.root)
    normalized_by_execution_id = (
        normalized_execution_cache
        if normalized_execution_cache is not None
        else {}
    )
    normalized_steps: list[StepPortfolioResult] = []
    updated_steps = list(result.run.steps)
    for step_run, step_result in zip(result.run.steps, result.steps):
        if step_run.step_index < len(preserved_steps):
            normalized_steps.append(preserved_steps[step_run.step_index])
            continue
        step = result.run.step_at(step_run.step_index)
        if isinstance(step, (DeriveStep, MatchStep)):
            normalized_steps.append(
                normalize_step_execution(
                    step_result,
                    validate_semantic_model=validate_semantic_model,
                )
            )
            continue
        if isinstance(step, FilterStep):
            diagnostics: list[str] = []
            source = normalized_steps[step_run.candidate_input_from.step_index]
            evidence = _component_empty_evidence(result.run, result.steps, source.portfolios,
                                                  step_run.step_index, graph, registry)
            evidence.update(_detection_collection_evidence(
                result.run, result.steps, source.portfolios, step_run.step_index, graph, registry,
                normalized_by_execution_id,
            ))
            view = _filter_candidate_view(step, step_run, normalized_steps, diagnostics=diagnostics,
                                          collection_evidence=evidence)
            if diagnostics:
                updated_steps[step_run.step_index] = step_run.model_copy(update={
                    "warnings": step_run.warnings + tuple(
                        message for message in diagnostics if message not in step_run.warnings),
                })
            normalized_steps.append(
                apply_deferred_search_selection(
                    result.run.workflow, view,
                    {item.step_index: item for item in normalized_steps}, result.run.steps,
                )
            )
            continue
        diagnostics = []
        own = _normalize_planned_step(
            step_result,
            step_run,
            result.run,
            normalized_by_execution_id,
            validate_semantic_model=validate_semantic_model, diagnostics=diagnostics,
        )
        if diagnostics:
            updated_steps[step_run.step_index] = step_run.model_copy(update={
                "warnings": step_run.warnings + tuple(
                    message for message in diagnostics if message not in step_run.warnings),
            })
        normalized_steps.append(
            apply_classification_selection(step, _materialize_enrichment_view(
                step_run, apply_search_selection(step, apply_time_selection(step, step_run, own), step_run), normalized_steps,
            ))
        )

    return WorkflowPortfolioResult(
        run=(result.run if tuple(updated_steps) == result.run.steps else
             result.run.model_copy(update={"steps": tuple(updated_steps)})),
        steps=tuple(normalized_steps),
    )


__all__ = [
    "WorkflowNormalizationAlignmentError",
    "apply_classification_selection",
    "normalize_execution",
    "normalize_step_execution",
    "normalize_workflow_execution",
]
