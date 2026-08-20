"""Minimal Streamlit front end for the declarative DSL compiler pipeline."""

from __future__ import annotations

import streamlit as st

from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import (
    DSLParseError,
    SurfaceCapabilityStatus,
    SurfaceCapabilityValidationError,
    SurfaceLoweringError,
    compile_surface,
    parse_surface_script,
    validate_surface_capabilities,
    validate_surface_semantics,
)


_EXAMPLE = """objects from lsst via alerce
    within 7d
    latest 100
    with classification from lc_classifier:
        best.class = "SN"
        best.probability >= 0.8
    order by summary.time.last_mjd desc
"""


def main() -> None:
    """Render syntax, ontology, capability, IR, and result-view compilation."""

    st.title("Alertissimo DSL")
    st.markdown(
        "Validate the formal declarative syntax, ontology-grounded surface intent, "
        "registered provider capabilities, scientific WorkflowIR, and separate "
        "result-view intent. Planning, binding, and execution remain later stages."
    )

    dsl_input = st.text_area("DSL", value=_EXAMPLE, height=300)
    if not st.button("Validate and compile"):
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

    graph = build_capability_graph()
    try:
        capability_report = validate_surface_capabilities(surface, graph=graph)
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

    try:
        compilation = compile_surface(surface, graph=graph)
    except SurfaceLoweringError as exc:
        st.warning(f"Lowering is not yet available for all intent: {exc}")
    else:
        st.success("Surface intent compiled")
        st.subheader("Scientific WorkflowIR")
        st.json(compilation.workflow.model_dump(mode="json"))
        st.subheader("Result view")
        st.json(compilation.view.model_dump(mode="json"))

    st.subheader("Surface intent")
    st.json(surface.model_dump(mode="json"))
    st.info(
        "Result-view instructions are kept outside scientific WorkflowIR and "
        "Portfolio content. This UI stops before endpoint planning, parameter "
        "binding, and provider execution."
    )


if __name__ == "__main__":
    main()
