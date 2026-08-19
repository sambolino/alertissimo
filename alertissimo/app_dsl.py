"""Minimal Streamlit front end for the declarative DSL surface."""

from __future__ import annotations

import streamlit as st

from alertissimo.dsl import (
    DSLParseError,
    parse_surface_script,
    validate_surface_semantics,
)


_EXAMPLE = """objects from lsst via fink
    within 7d
    latest 100
    where classification = "SN Ia"
    with lightcurve
    with crossmatch from gaia
    order by summary.photometry.r.mag.mean asc
"""


def main() -> None:
    """Render a parser and static-validation UI for the production DSL surface."""

    st.title("Alertissimo DSL")
    st.markdown(
        "Parse the formal declarative syntax, inspect preserved user intent, and "
        "run ontology-level static validation. Provider capability resolution and "
        "WorkflowIR lowering remain separate stages."
    )

    dsl_input = st.text_area("DSL", value=_EXAMPLE, height=280)
    if not st.button("Validate"):
        return

    try:
        surface = parse_surface_script(dsl_input)
    except DSLParseError as exc:
        st.error(f"DSL syntax error: {exc}")
        return

    st.success("Formal syntax is valid")
    report = validate_surface_semantics(surface)
    if report.errors:
        st.error("Ontology validation failed")
        for issue in report.errors:
            st.markdown(f"- `{issue.code}`: {issue.message}")
    else:
        st.success("Ontology-grounded surface intent is valid")

    for issue in report.warnings:
        st.warning(f"{issue.code}: {issue.message}")

    st.subheader("Surface intent")
    st.json(surface.model_dump(mode="json"))
    st.info(
        "This UI deliberately stops before capability validation, planning, and "
        "execution."
    )


if __name__ == "__main__":
    main()
