"""Broker headline derivation and immutable materialization over native evidence.

Provider policy and vocabulary live beside provider mappings. No network calls or
cross-method scoring; native best fields and earlier views remain unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import yaml

from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.representations import (
    InternalPortfolioId, InternalRecordId, Portfolio, SemanticRecord,
)


class HeadlinePolicyError(ValueError):
    """A reviewed policy is malformed; never treat this as missing evidence."""


SCOPES = frozenset({"candidate", "catalogue_association"})
STATUSES = frozenset({"candidate", "reported", "unknown"})
# These paths belong to the separate derived headline record, never a native
# producer's best.class/probability fields. Shared by material capability checks.
HEADLINE_FIELDS = frozenset("best." + name for name in (
    "native_class", "taxon", "scope", "basis",
    "candidate_status", "subtype", "source_method", "source_version",
    "source_output", "native_probability", "native_score", "policy",
    "mapping_version", "policy_digest", "status", "error_code", "broker",
    "survey", "object_id", "input_record_ids", "considered_record_ids",
    "eligible_record_ids", "selected_record_ids", "observation_mjd", "evidence_digest",
))


def is_headline_record(record: SemanticRecord) -> bool:
    return record.semantic_type.startswith("classification@headline:")


def headline_reference(reference) -> bool:
    return (reference.semantic_type == "classification"
            and reference.producer in (None, "headline")
            and reference.field_path in HEADLINE_FIELDS)


def headline_material_available(reference, outputs) -> bool:
    """Prove derivability from mapped candidate classification, not field presence.

    An eligible route may return no label; its stored status then reports missing.
    Physical mappings remain physical: no synthetic mapping/pushdown is registered.
    """
    if not headline_reference(reference):
        return False
    pairs = {(field.broker, field.origin) for field in outputs
             if field.semantic_record_type.partition("@")[0] == "classification"
             and reference.channel in (None, field.broker)}
    return any((PROVIDERS_ROOT / broker / origin / "classification_headline.yaml").is_file()
               for broker, origin in pairs)


def materialize_headlines(portfolio: Portfolio, *, include_missing: bool = False) -> Portfolio:
    """Store one immutable interpretation per delivered broker/survey.

    Reuse a stored result when its native evidence is unchanged, even if current
    policy data changed. Deserialization/presentation never call this function.
    New material replaces derived records only in the new view; native records
    and the old view remain intact. No synthetic physical execution is invented.
    """
    native = tuple(r for r in portfolio.records if not is_headline_record(r))
    stored = tuple(r for r in portfolio.records if is_headline_record(r))
    headlines = []
    for broker, origin in sorted({(e.broker, e.origin) for e in portfolio.executions}):
        if not (PROVIDERS_ROOT / broker / origin / "classification_headline.yaml").is_file():
            continue
        # Only identities belonging to this survey may acquire this headline.
        if not any(r.semantic_type.partition(":")[0] == f"summary@{origin}"
                   and r.get("identity.object_id") is not None for r in native):
            continue
        execution_ids = {e.internal_execution_id for e in portfolio.executions
                         if (e.broker, e.origin) == (broker, origin)}
        if not include_missing and not any(
            r.semantic_type.partition("@")[0] == "classification"
            and r.internal_source is not None and r.internal_source.internal_execution_id in execution_ids
            for r in native
        ) and not any(r.get("best.broker") == broker and r.get("best.survey") == origin for r in stored):
            continue
        inputs = tuple(r for r in native if r.semantic_type.partition("@")[0] == "classification"
                       and r.internal_source is not None
                       and r.internal_source.internal_execution_id in execution_ids)
        linked = tuple(r for r in native if r.semantic_type.partition("@")[0] == "measurement"
                       and r.internal_source is not None
                       and any(r.internal_source == c.internal_source for c in inputs))
        identities = sorted({str(r.get("identity.object_id")) for r in native
                             if r.semantic_type.partition(":")[0] == f"summary@{origin}"
                             and r.get("identity.object_id") is not None})
        evidence = (identities, sorted((r.internal_record_id.value, r.semantic_type, dict(r.fields))
                                      for r in inputs + linked))
        fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()
        previous = [r for r in stored if r.get("best.broker") == broker
                    and r.get("best.survey") == origin
                    and r.get("best.evidence_digest") == fingerprint]
        if len(previous) == 1:
            headlines.append(previous[0])
            continue
        fields = derive_headline_fields(portfolio, broker=broker, origin=origin)
        fields["best.evidence_digest"] = fingerprint
        digest = hashlib.sha256(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()
        headlines.append(SemanticRecord(InternalRecordId(f"headline:{digest}"),
                                        f"classification@headline:{broker}", fields))
    records = native + tuple(headlines)
    if records == portfolio.records:
        return portfolio
    # New immutable content needs a new Portfolio ID; retain incident edges.
    digest = hashlib.sha256((portfolio.internal_portfolio_id.value + ":" + ":".join(
        r.internal_record_id.value for r in headlines)).encode()).hexdigest()
    identifier = InternalPortfolioId(f"portfolio:headline:{digest}")
    removed = {r.internal_record_id for r in stored} - {r.internal_record_id for r in headlines}
    edges = tuple(replace(edge,
                         subject=identifier if edge.subject == portfolio.internal_portfolio_id else edge.subject,
                         target=identifier if edge.target == portfolio.internal_portfolio_id else edge.target)
                  for edge in portfolio.edges if edge.subject not in removed and edge.target not in removed)
    return replace(portfolio, internal_portfolio_id=identifier, records=records, edges=edges)


def _key(value):
    # A numeric code and its string spelling are different upstream values.
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def validate_taxonomy(taxonomy: Mapping) -> None:
    """Reject ambiguous identifiers and malformed explicit ancestry on load."""
    if not isinstance(taxonomy, Mapping) or set(taxonomy) != {
        "schema_version", "taxonomy_id", "nodes", "aliases",
    } or type(taxonomy["schema_version"]) is not int or taxonomy["schema_version"] != 1:
        raise HeadlinePolicyError("invalid taxonomy schema")
    if not isinstance(taxonomy["taxonomy_id"], str) or not taxonomy["taxonomy_id"]:
        raise HeadlinePolicyError("taxonomy requires an identifier")
    if not isinstance(taxonomy["nodes"], list) or not taxonomy["nodes"]:
        raise HeadlinePolicyError("taxonomy requires nodes")
    nodes = {}
    for node in taxonomy["nodes"]:
        if not isinstance(node, dict) or not {"code", "name", "parent", "origin"} <= node.keys() or set(node) - {
            "code", "name", "parent", "origin", "used_for",
        }:
            raise HeadlinePolicyError("invalid taxonomy node")
        code = node["code"]
        if type(code) is not int or code in nodes:
            raise HeadlinePolicyError("duplicate or invalid taxonomy code")
        if not isinstance(node["name"], str) or not node["name"]:
            raise HeadlinePolicyError("taxonomy node requires a name")
        if node["parent"] is not None and type(node["parent"]) is not int:
            raise HeadlinePolicyError("invalid taxonomy parent")
        if node["origin"] not in {"elasticc", "alertissimo"} or (
            node["origin"] == "alertissimo" and not 9000 <= code <= 9399
        ):
            raise HeadlinePolicyError("invalid taxonomy origin or extension range")
        if node["name"].endswith("/Other") and (
            not isinstance(node.get("used_for"), str) or not node["used_for"].strip()
        ):
            raise HeadlinePolicyError("/Other requires used_for")
        nodes[code] = node
    for code in nodes:
        seen = set()
        while code is not None:
            if code not in nodes:
                raise HeadlinePolicyError("taxonomy parent does not exist")
            if code in seen:
                raise HeadlinePolicyError("taxonomy ancestry contains a cycle")
            seen.add(code)
            code = nodes[code]["parent"]
    if not isinstance(taxonomy["aliases"], list):
        raise HeadlinePolicyError("taxonomy aliases must be a list")
    aliases = set()
    for row in taxonomy["aliases"]:
        if not isinstance(row, dict) or not {"alias", "codes"} <= row.keys() or set(row) - {"alias", "codes", "note"}:
            raise HeadlinePolicyError("invalid taxonomy alias")
        alias = row["alias"].strip().casefold() if isinstance(row["alias"], str) else ""
        if not alias or alias in aliases:
            raise HeadlinePolicyError("duplicate or invalid taxonomy alias")
        aliases.add(alias)
        codes = row["codes"]
        if not isinstance(codes, list) or not codes or any(type(c) is not int or c not in nodes for c in codes):
            raise HeadlinePolicyError("alias refers to invalid taxonomy codes")
        if len(set(codes)) != len(codes):
            raise HeadlinePolicyError("duplicate alias codes")


@lru_cache(maxsize=1)
def load_taxonomy() -> dict:
    path = PROVIDERS_ROOT.parent / "semantic_model" / "classification_taxonomy.yaml"
    try:
        taxonomy = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise HeadlinePolicyError("cannot read classification taxonomy") from exc
    validate_taxonomy(taxonomy)
    return taxonomy


def resolve_taxon(value) -> tuple[int, ...]:
    """Resolve a surface literal once; the frozen IR never retains aliases."""
    from difflib import get_close_matches

    aliases = {row["alias"].strip().casefold(): tuple(sorted(row["codes"]))
               for row in load_taxonomy()["aliases"]}
    key = str(value).strip().casefold() if type(value) in (str, int) else ""
    if key not in aliases:
        suggestions = get_close_matches(key, aliases, n=5)
        raise ValueError(f"Unknown classification taxon {value!r}. Closest aliases: {', '.join(suggestions) or 'none'}")
    return aliases[key]


def compare_taxa(record_codes, query_codes: tuple[int, ...], operator: str = "=") -> bool | None:
    """Compare code sets using explicit parent links and three-valued logic."""
    parents = {node["code"]: node["parent"] for node in load_taxonomy()["nodes"]}
    if not isinstance(record_codes, (tuple, list)) or not record_codes or any(
        type(code) is not int or code not in parents for code in record_codes
    ):
        return None
    if not isinstance(query_codes, tuple) or not query_codes or any(
        type(code) is not int or code not in parents for code in query_codes
    ):
        raise HeadlinePolicyError("taxon comparison requires resolved dictionary codes")
    if operator not in {"=", "!="}:
        raise HeadlinePolicyError("taxon comparison only supports = and !=")

    def under(code, ancestor):
        while code is not None:
            if code == ancestor:
                return True
            code = parents[code]
        return False

    if all(any(under(r, q) for q in query_codes) for r in record_codes):
        result = True
    elif not any(under(r, q) or under(q, r) for r in record_codes for q in query_codes):
        result = False
    else:
        return None
    return result if operator == "=" else not result


def format_taxa(codes) -> str | None:
    """Format stored codes without deriving or selecting any scientific result."""
    if not codes:
        return None
    nodes = {node["code"]: node for node in load_taxonomy()["nodes"]}
    return "; ".join(
        f"{code} {nodes[code]['name']}" + (" (Alertissimo ext.)" if nodes[code]["origin"] == "alertissimo" else "")
        if code in nodes else str(code) for code in codes
    )


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
        if not isinstance(row, dict) or set(row) - {"label", "codes", "scope", "status", "subtype"}:
            raise HeadlinePolicyError("invalid vocabulary row")
        key = _key(row.get("label"))
        if key is None or key in labels:
            raise HeadlinePolicyError("duplicate or invalid vocabulary label")
        labels.add(key)
        if row.get("scope") not in SCOPES or row.get("status") not in STATUSES:
            raise HeadlinePolicyError("vocabulary must specify scope and candidate status")
        codes = row.get("codes")
        if "codes" not in row:
            raise HeadlinePolicyError("vocabulary requires codes")
        if row["scope"] == "catalogue_association":
            if codes is not None:
                raise HeadlinePolicyError("catalogue association codes must be null")
        else:
            nodes = {node["code"]: node for node in load_taxonomy()["nodes"]}
            if not isinstance(codes, list) or not codes or any(
                type(code) is not int or code not in nodes for code in codes
            ) or len(set(codes)) != len(codes):
                raise HeadlinePolicyError("candidate codes must be a nonempty set of dictionary integers")
            for code in codes:
                node = nodes[code]
                if node["name"].endswith("/Other") and node["used_for"] == "unused":
                    raise HeadlinePolicyError("referenced /Other code needs a documented used_for meaning")
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
    lookup entries produce ``best.taxon``; catalogue labels carry no proposition.
    Every unavailable/error outcome has an explicit status.
    No probability threshold, cross-method maximum, version ordering or retrieval
    timestamp is used. Label-contract versions with the same label agree and
    retain every reported version.
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
        signatures = {(_key(label), _key(r.get("provenance.producer.version"))
                       if method["version_rule"] == "exact" else None)
                      for r, _, label in candidates}
        if len(signatures) != 1:
            return dict(result, **{"best.status": "conflict"})
        record, output, label = candidates[0]
        result.update({"best.native_class": label, "best.source_version": record.get("provenance.producer.version"),
                       "best.selected_record_ids": tuple(sorted({r.internal_record_id.value for r, _, _ in candidates})),
                       "best.source_output": output})
        versions = {_key(r.get("provenance.producer.version")) for r, _, _ in candidates}
        if method["version_rule"] == "label_contract" and len(versions) > 1:
            # Missing versions remain explicit rather than inventing a model version.
            result["best.source_version"] = tuple(sorted(
                "null" if version is None else version for version in versions))
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
        if row["scope"] != "candidate" or row["codes"] is None:
            return dict(result, **{"best.status": "recognized_no_proposition"})
        result["best.taxon"] = tuple(sorted(row["codes"]))
        result["best.status"] = "available"
        return result
    return result
