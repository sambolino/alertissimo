"""Minimal Streamlit front end for the declarative DSL surface."""

from __future__ import annotations

import streamlit as st

from alertissimo.dsl import DSLParseError, parse_surface_script


_EXAMPLE = """objects from lsst via fink
    within 7d
    latest 100
    where classification = \"SN Ia\"
    with lightcurve
    with crossmatch from gaia
    order by summary.photometry.r.mag.mean asc
"""


def main() -> None:
    """Render a small parser/inspection UI for the production DSL surface."""

    st.title("Alertissimo DSL")
    st.markdown(
        "Parse the declarative user-facing DSL and inspect the preserved surface "
        "intent. Capability validation and WorkflowIR lowering are intentionally "
        "separate later stages."
    )

    dsl_input = st.text_area("DSL", value=_EXAMPLE, height=280)

    if not st.button("Parse"):
        return

    try:
        surface = parse_surface_script(dsl_input)
    except DSLParseError as exc:
        st.error(f"DSL parse error: {exc}")
        return

    st.success("DSL parsed successfully")
    st.subheader("Surface intent")
    st.json(surface.model_dump(mode="json"))
    st.info(
        "This UI stops at the DSL surface. Ontology validation, capability "
        "validation, planning, and execution are not wired here yet."
    )


if __name__ == "__main__":
    main()
