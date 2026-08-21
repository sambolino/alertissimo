#!/usr/bin/env python3
"""Live ANTARES ZTF+LSST lookup -> normalization smoke test."""

from __future__ import annotations

from alertissimo.data_layer.execution import RegistryEndpointExecutor
from alertissimo.orchestration.normalization import normalize_execution


CASES = (
    (
        "ztf",
        "get_by_ztf_object_id",
        {"ztf_object_id": "ZTF20aafqubg"},
    ),
    (
        "lsst",
        "get_by_lsst_dia_object_id",
        {"lsst_object_id": "170587117485817955"},
    ),
)


def _summary_ids(portfolios) -> tuple[str, ...]:
    seen: list[str] = []
    for portfolio in portfolios:
        for record in portfolio.records:
            if record.semantic_type.split("@", 1)[0] != "summary":
                continue
            value = record.fields.get("identity.object_id")
            if value is not None and str(value) not in seen:
                seen.append(str(value))
    return tuple(seen)


def main() -> int:
    executor = RegistryEndpointExecutor()

    print("=== ANTARES LIVE LOOKUP + NORMALIZATION ===")
    for origin, endpoint, params in CASES:
        print(f"\n{origin}: antares/{origin}/{endpoint} params={params}")
        execution = executor.execute("antares", origin, endpoint, params)
        portfolios = normalize_execution(execution, validate_semantic_model=True)
        if not portfolios:
            raise RuntimeError(
                f"antares/{origin}/{endpoint} returned no normalized Portfolio"
            )

        semantic_types = sorted(
            {record.semantic_type for portfolio in portfolios for record in portfolio.records}
        )
        print(f"  portfolios={len(portfolios)}")
        print(f"  object_ids={list(_summary_ids(portfolios))}")
        print(f"  semantic_types={semantic_types}")

    print("\nANTARES LIVE ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
