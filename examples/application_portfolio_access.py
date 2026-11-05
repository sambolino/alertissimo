"""Small consumer example; helpers here are not additional Alertissimo APIs.

From the checkout: PYTHONPATH=. python examples/application_portfolio_access.py
    workflow.dsl [--origin ztf --object-id ZTF...]

Execution contacts the providers named in the supplied DSL. Importing this module
does not execute a workflow. See docs/application_portfolio_access.md.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from alertissimo.api import execute_dsl
from alertissimo.data_layer.representations import InternalRecordSource, Portfolio, SemanticRecord
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict, portfolio_to_json


def candidate_identity(portfolio: Portfolio) -> tuple[str, str]:
    """Require one qualified survey/object identity, across all summary records."""
    identities = set()
    for record in portfolio.records:
        noun, _, qualifier = record.semantic_type.partition("@")
        if noun != "summary":
            continue
        origin, separator, channel = qualifier.partition(":")
        object_id = record.get("identity.object_id")
        if (not origin or origin == "unknown" or not separator or not channel
                or not isinstance(object_id, (str, int)) or isinstance(object_id, bool)
                or not str(object_id).strip()):
            raise ValueError("candidate summary lacks a qualified survey/object identity")
        identities.add((origin, str(object_id)))
    if len(identities) != 1:
        raise ValueError(f"expected one candidate identity, found {sorted(identities)!r}")
    return next(iter(identities))


def select_candidate(
    portfolios: Iterable[Portfolio], *, origin: str, object_id: str,
) -> Portfolio:
    """Select, never rename, a candidate; missing or duplicate matches are errors."""
    matches = [p for p in portfolios if candidate_identity(p) == (origin, object_id)]
    if len(matches) != 1:
        raise ValueError(f"expected one Portfolio for {(origin, object_id)!r}, found {len(matches)}")
    return matches[0]


def record_frame(portfolio: Portfolio, noun: str) -> pd.DataFrame:
    """View every record in a family with qualified type and source-row metadata.

    Semantic columns use a fields. prefix, audit columns a source. prefix. Object
    dtype keeps integer identifiers exact when other rows have missing values.
    The canonical Portfolio/JSON remains authoritative for absent versus null.
    """
    rows = []
    for record in portfolio_to_dict(portfolio)["records"]:
        if record["semantic_type"].split("@", 1)[0] != noun:
            continue
        rows.append({
            "internal_record_id": record["internal_record_id"],
            "semantic_type": record["semantic_type"],
            **{f"source.{key}": value for key, value in (record["internal_source"] or {}).items()},
            **{f"fields.{key}": value for key, value in record["fields"].items()},
        })
    return pd.DataFrame(rows, dtype=object)


def classification_records(
    portfolio: Portfolio, *, semantic_type: str, version: str | None = None,
    source: InternalRecordSource | None = None,
) -> tuple[SemanticRecord, ...]:
    """Select an exact qualified assertion type, optionally version and source row.

    Return every match. No payload order, retrieval time, or version spelling is
    interpreted as a newest assertion. A source-row condition can correlate a
    classification with a measurement chosen by an application's time policy.
    """
    if not semantic_type.startswith("classification@") or not semantic_type.partition("@")[2]:
        raise ValueError("provide an exact qualified classification semantic type")
    return tuple(
        record for record in portfolio.records_of_type(semantic_type)
        if (version is None or record.get("provenance.producer.version") == version)
        and (source is None or record.internal_source == source)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", type=Path, help="file containing a complete DSL workflow")
    parser.add_argument("--origin", help="survey of the candidate to select")
    parser.add_argument("--object-id", help="exact candidate ID; requires --origin")
    args = parser.parse_args()
    if (args.origin is None) != (args.object_id is None):
        parser.error("--origin and --object-id must be supplied together")
    result = execute_dsl(args.workflow.read_text(encoding="utf-8"), continue_from=None)
    portfolios = result.portfolios
    if args.object_id is not None:
        portfolios = (select_candidate(portfolios, origin=args.origin, object_id=args.object_id),)
    for portfolio in portfolios:
        candidate_identity(portfolio)
        # One canonical JSON document per line, retaining all records and audit.
        print(portfolio_to_json(portfolio, indent=None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
