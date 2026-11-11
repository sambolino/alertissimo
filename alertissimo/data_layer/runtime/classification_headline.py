"""Pure, opt-in broker headline derivation over canonical classification records.

Provider policy and vocabulary live beside provider mappings. This module neither
fetches evidence nor changes a Portfolio. The execution/view integration is a
separate change; importing it does not alter native ``best`` query semantics.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import yaml

from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.representations import Portfolio, SemanticRecord


class HeadlinePolicyError(ValueError):
    """A reviewed policy is malformed; never treat this as missing evidence."""


SCOPES = frozenset({"candidate", "catalogue_association"})
STATUSES = frozenset({"candidate", "reported", "unknown"})
COARSE_CLASSES = frozenset({
    "supernova", "agn", "variable_star", "solar_system", "microlensing",
    "kilonova", "tidal_disruption", "cataclysmic_variable", "artifact",
    "satellite", "transient", "periodic", "stochastic", "nonperiodic",
    "fast_transient", "long_transient", "star", "galaxy", "nuclear_transient",
})


def _key(value):
    # A numeric code and its string spelling are different upstream values.
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def validate_policy(policy: Mapping) -> None:
    """Check the complete finite vocabulary and selection declaration eagerly."""
    if not isinstance(policy, Mapping):
        raise HeadlinePolicyError("headline policy must be a mapping")
    required = {"schema_version", "policy_id", "mapping_version", "broker", "origin",
                "sources", "methods", "vocabulary", "sentinels", "enabled"}
    if set(policy) - required - {"note"} or required - set(policy):
        raise HeadlinePolicyError("unexpected or missing headline policy keys")
    if type(policy["schema_version"]) is not int or policy["schema_version"] != 1:
        raise HeadlinePolicyError("unsupported headline policy schema")
    for name in ("policy_id", "mapping_version", "broker", "origin"):
        if not isinstance(policy[name], str) or not policy[name]:
            raise HeadlinePolicyError(f"{name} must be a nonempty string")
    if type(policy["enabled"]) is not bool:
        raise HeadlinePolicyError("enabled must be boolean")
    if not isinstance(policy["sources"], list) or not policy["sources"] or not all(
        isinstance(s, str) and s for s in policy["sources"]
    ):
        raise HeadlinePolicyError("policy requires vocabulary/selection sources")
    if not isinstance(policy["methods"], list):
        raise HeadlinePolicyError("methods must be an ordered list")
    producers = set()
    for method in policy["methods"]:
        if not isinstance(method, dict) or set(method) - {
            "producer", "versions", "version_rule", "basis", "input_survey_field",
            "latest_observation", "allow_rank_one",
        } or not {"producer", "version_rule", "basis"} <= set(method):
            raise HeadlinePolicyError("invalid method declaration")
        producer = method["producer"]
        if not isinstance(producer, str) or not producer or producer in producers:
            raise HeadlinePolicyError("method producers must be unique nonempty strings")
        producers.add(producer)
        if method["version_rule"] not in {"label_contract", "exact"}:
            raise HeadlinePolicyError("unknown version compatibility rule")
        if method["version_rule"] == "exact" and (
            not isinstance(method.get("versions"), list) or not method["versions"]
            or any(_key(v) is None for v in method["versions"])
        ):
            raise HeadlinePolicyError("exact version rule requires explicit versions")
        if method["basis"] not in {"model", "contextual", "broker_composite"}:
            raise HeadlinePolicyError("unknown assessment basis")
        for flag in ("latest_observation", "allow_rank_one"):
            if flag in method and type(method[flag]) is not bool:
                raise HeadlinePolicyError(f"{flag} must be boolean")
        if "input_survey_field" in method and not isinstance(method["input_survey_field"], str):
            raise HeadlinePolicyError("input survey field must be a semantic field path")
    if policy["enabled"] and not policy["methods"]:
        raise HeadlinePolicyError("enabled policy requires a method")
    if not isinstance(policy["vocabulary"], list) or not isinstance(policy["sentinels"], list):
        raise HeadlinePolicyError("vocabulary and sentinels must be lists")
    labels = set()
    for row in policy["vocabulary"]:
        if not isinstance(row, dict) or set(row) - {"label", "coarse", "scope", "status", "subtype"}:
            raise HeadlinePolicyError("invalid vocabulary row")
        key = _key(row.get("label"))
        if key is None or key in labels:
            raise HeadlinePolicyError("duplicate or invalid vocabulary label")
        labels.add(key)
        if row.get("scope") not in SCOPES or row.get("status") not in STATUSES:
            raise HeadlinePolicyError("vocabulary must specify scope and candidate status")
        if row.get("coarse") is not None and row["coarse"] not in COARSE_CLASSES:
            raise HeadlinePolicyError("coarse class is not in the finite proposition set")
    for sentinel in policy["sentinels"]:
        key = _key(sentinel)
        if key is None or key in labels:
            raise HeadlinePolicyError("duplicate sentinel or vocabulary/sentinel overlap")
        labels.add(key)


@lru_cache(maxsize=32)
def _policy_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_policy(broker: str, origin: str, *, providers_root: Path = PROVIDERS_ROOT) -> dict:
    """Read packaged, versioned data; no network lookup or mutable remote defaults."""
    if any(not name or not name.replace("_", "").isalnum() for name in (broker, origin)):
        raise HeadlinePolicyError("invalid provider identity")
    path = providers_root / broker / origin / "classification_headline.yaml"
    try:
        policy = yaml.safe_load(_policy_text(str(path)))
    except (OSError, yaml.YAMLError) as exc:
        raise HeadlinePolicyError(f"cannot read headline policy for {broker}/{origin}") from exc
    validate_policy(policy)
    if (policy["broker"], policy["origin"]) != (broker, origin):
        raise HeadlinePolicyError("policy provider identity does not match its location")
    return policy


def _producer(record: SemanticRecord) -> str | None:
    noun, _, qualifier = record.semantic_type.partition("@")
    return qualifier.partition(":")[0] if noun == "classification" else None


def _outputs(record: SemanticRecord, allow_rank_one: bool):
    if record.get("best.class") is not None:
        return [("best", record.get("best.class"))]
    if not allow_rank_one:
        return []
    return [(key[:-6], value) for key, value in record.fields.items()
            if key.startswith("assessment.") and key.endswith(".class") and value is not None
            and type(record.get(key[:-6] + ".rank")) in (int, float)
            and record.get(key[:-6] + ".rank") == 1]


def _observation_time(portfolio: Portfolio, record: SemanticRecord):
    times = {r.get("time.mjd") for r in portfolio.records
             if r.semantic_type.partition("@")[0] == "measurement"
             and record.internal_source is not None and r.internal_source == record.internal_source
             and type(r.get("time.mjd")) in (int, float) and math.isfinite(r.get("time.mjd"))}
    return next(iter(times)) if len(times) == 1 else None


def derive_headline_fields(portfolio: Portfolio, *, broker: str, origin: str,
                           policy: Mapping | None = None) -> dict:
    """Return attributable fields for one broker/survey, leaving all inputs intact.

    ``best.native_class`` preserves the selected native label. Only candidate-scoped
    lookup entries produce ``best.coarse_class``; catalogue labels can produce
    ``best.context_class``. Every unavailable/error outcome has an explicit status.
    No probability threshold, cross-method maximum, version ordering or retrieval
    timestamp is used. Identical labels across different model versions still do
    not establish a uniquely selected version.
    """
    policy = load_policy(broker, origin) if policy is None else policy
    validate_policy(policy)
    if (policy["broker"], policy["origin"]) != (broker, origin):
        raise HeadlinePolicyError("wrong policy for requested broker/survey")
    digest = hashlib.sha256(json.dumps(dict(policy), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    result = {"best.policy": policy["policy_id"], "best.mapping_version": policy["mapping_version"],
              "best.policy_digest": digest, "best.status": "missing", "best.broker": broker,
              "best.survey": origin}
    identities = {str(r.get("identity.object_id")) for r in portfolio.records
                  if r.semantic_type.partition(":")[0] == f"summary@{origin}"
                  and r.get("identity.object_id") is not None}
    # Delivery provenance is required. A channel spelling alone cannot prove
    # which survey or physical execution supplied a record.
    inputs = []
    for record in portfolio.records:
        if _producer(record) is None or record.internal_source is None:
            continue
        channel = record.semantic_type.partition(":")[2]
        if channel and channel != broker:
            continue
        execution = portfolio.execution(record.internal_source.internal_execution_id)
        if execution is not None and (execution.broker, execution.origin) == (broker, origin):
            inputs.append(record)
    result["best.input_record_ids"] = tuple(sorted(r.internal_record_id.value for r in inputs))
    if not policy["enabled"]:
        return dict(result, **{"best.status": "headline_unresolved"})
    if len(identities) != 1:
        return dict(result, **{"best.status": "identity_unresolved"})
    result["best.object_id"] = next(iter(identities))
    for method in policy["methods"]:
        records = [r for r in inputs if _producer(r) == method["producer"]]
        candidates = [(r, output, label) for r in records
                      for output, label in _outputs(r, method.get("allow_rank_one", False))]
        if not candidates:
            continue
        result.update({"best.source_method": method["producer"], "best.basis": method["basis"]})
        result["best.considered_record_ids"] = tuple(sorted({r.internal_record_id.value for r, _, _ in candidates}))
        # A present but incompatible preferred method does not silently fall back.
        if field := method.get("input_survey_field"):
            if any(r.get(field) != origin for r, _, _ in candidates):
                return dict(result, **{"best.status": "input_scope_unresolved"})
        if method["version_rule"] == "exact":
            supported = [item for item in candidates
                         if _key(item[0].get("provenance.producer.version")) in {_key(v) for v in method["versions"]}]
            if not supported:
                return dict(result, **{"best.status": "unsupported_version"})
            candidates = supported
        result["best.eligible_record_ids"] = tuple(sorted({r.internal_record_id.value for r, _, _ in candidates}))
        # A broker's selected summary takes precedence over its probability table.
        selected = [item for item in candidates if item[1] == "best"]
        if selected:
            candidates = selected
        if method.get("latest_observation") and len(candidates) > 1:
            dated = [(_observation_time(portfolio, item[0]), item) for item in candidates]
            if any(time is None for time, _ in dated):
                return dict(result, **{"best.status": "observation_order_unresolved"})
            latest = max(time for time, _ in dated)
            candidates = [item for time, item in dated if time == latest]
            result["best.observation_mjd"] = latest
        signatures = {(_key(label), _key(r.get("provenance.producer.version"))) for r, _, label in candidates}
        if len(signatures) != 1:
            return dict(result, **{"best.status": "conflict"})
        record, output, label = candidates[0]
        result.update({"best.native_class": label, "best.source_version": record.get("provenance.producer.version"),
                       "best.selected_record_ids": tuple(sorted({r.internal_record_id.value for r, _, _ in candidates})),
                       "best.source_output": output})
        # Do not select one metric among duplicate label witnesses.
        for metric in ("probability", "score"):
            values = {_key(r.get(path + "." + metric)) for r, path, _ in candidates}
            value = record.get(output + "." + metric)
            if len(values) == 1 and type(value) in (int, float) and math.isfinite(value):
                result["best.native_" + metric] = value
        key = _key(label)
        if key in {_key(v) for v in policy["sentinels"]}:
            return dict(result, **{"best.status": "sentinel"})
        row = next((v for v in policy["vocabulary"] if _key(v["label"]) == key), None)
        if row is None:
            return dict(result, **{"best.status": "error", "best.error_code": "unmapped_label"})
        result.update({"best.scope": row["scope"], "best.candidate_status": row["status"]})
        if row.get("subtype") is not None:
            result["best.subtype"] = row["subtype"]
        if row.get("coarse") is None:
            return dict(result, **{"best.status": "recognized_no_proposition"})
        field = "best.coarse_class" if row["scope"] == "candidate" else "best.context_class"
        result[field] = row["coarse"]
        result["best.status"] = "available" if row["scope"] == "candidate" else "context_only"
        return result
    return result
