"""Minimal Streamlit front end for the declarative DSL validation pipeline."""

from __future__ import annotations

import streamlit as st

from alertissimo.dsl import (
    DSLParseError,
    SurfaceCapabilityStatus,
    SurfaceCapabilityValidationError,
    parse_surface_script,
    validate_surface_capabilities,
    validate_surface_semantics,
)


_EXAMPLE = """objects from ztf via antares
    inside (34, 33, 0.5deg)
    within 7d
    latest 100
    with crossmatch from gaia
"""


def main() -> None:
    """Render syntax, ontology, and read-only capability validation."""

    st.title("Alertissimo DSL")
    st.markdown(
        "Validate the formal declarative syntax, ontology-grounded surface intent, "
        "and registered provider capabilities. Planning, binding, and execution "
        "remain separate later stages."
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
    semantic_report = validate_surface_semantics(surface)
    if semantic_report.errors:
        st.error("Ontology validation failed")
        for issue in semantic_report.errors:
            st.markdown(f"- `{issue.code}`: {issue.message}")
        return

    st.success("Ontology-grounded surface intent is valid")
    for issue in semantic_report.warnings:
        st.warning(f"{issue.code}: {issue.message}")

    try:
        capability_report = validate_surface_capabilities(surface)
    except SurfaceCapabilityValidationError as exc:
        st.error(f"Capability validation could not run: {exc}")
        return

    if capability_report.status is SurfaceCapabilityStatus.UNSUPPORTED:
        st.error("One or more registered capability requirements are unsupported")
    elif capability_report.status is SurfaceCapabilityStatus.DEFERRED:
        st.warning(
            "Provider capability validation passed where applicable, but one or "
            "more local/dynamic capabilities remain deferred"
        )
    else:
        st.success("Registered provider capabilities support the surface intent")

    st.subheader("Capability checks")
    st.json(capability_report.model_dump(mode="json"))

    st.subheader("Surface intent")
    st.json(surface.model_dump(mode="json"))
    st.info(
        "This UI deliberately stops before planning, parameter binding, and "
        "provider execution."
    )


if __name__ == "__main__":
    main()
