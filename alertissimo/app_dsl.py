"""Streamlit validation and planning of complete Alertissimo DSL workflows."""

from __future__ import annotations

import streamlit as st

from alertissimo.api import validate_dsl
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.dsl import DSLParseError, parse_surface_script
from alertissimo.orchestration.planner import PlanningError, plan_workflow


_EXAMPLE = """objects from ztf via lasair
inside (124.87996115142856, -6.0205001, 5arcsec)
with lightcurve via fink
"""


def main() -> None:
    """Validate through the public facade, then preview planning without execution."""

    st.set_page_config(page_title="Alertissimo · Validate a workflow", page_icon="🔭", layout="wide")
    st.title("Validate an investigation")
    st.write("Check an Alertissimo DSL workflow before running it against broker services.")
    st.caption("Validation and planning use the local registry. No broker requests are made.")

    with st.form("dsl-validation"):
        dsl_input = st.text_area("Complete workflow", value=_EXAMPLE, height=260)
        submitted = st.form_submit_button("Validate and plan", type="primary")
    if not submitted:
        return

    # This standalone page accepts complete workflows only. Do not let a fragment
    # inherit the facade's process-local active execution from another UI session.
    try:
        parse_surface_script(dsl_input)
    except DSLParseError as error:
        st.error(f"DSL syntax error: {error}")
        st.info("Start with `objects from ...` or `object ID from ...`.")
        return

    graph = build_capability_graph()
    validation = validate_dsl(dsl_input, graph=graph, name="UI workflow validation")
    if validation.parse_error is not None:
        st.error(f"DSL syntax error: {validation.parse_error}")
        return
    if validation.semantic is not None:
        for issue in validation.semantic.errors:
            st.error(f"{issue.code}: {issue.message}")
        for issue in validation.semantic.warnings:
            st.warning(f"{issue.code}: {issue.message}")
    if not validation.is_valid:
        return

    st.success("Syntax and scientific references are valid.")
    if validation.lowering_error is not None:
        st.warning(f"This workflow cannot currently run: {validation.lowering_error}")
    compilation = validation.compilation
    run = None
    if validation.is_runnable and compilation is not None:
        try:
            run = plan_workflow(compilation.workflow, graph)
        except PlanningError as error:
            st.warning(f"A complete execution plan is not available: {error}")
        else:
            st.success("The registry can produce an execution plan for this workflow.")
            st.caption(
                f"{len(compilation.workflow.steps)} workflow step(s). "
                "Provider availability, credentials, and returned data are checked when you execute."
            )

    with st.expander("Validation and planning details"):
        if validation.capabilities is not None:
            st.subheader("Capability checks")
            st.json(validation.capabilities.model_dump(mode="json"))
        if compilation is not None:
            st.subheader("Scientific workflow")
            st.json(compilation.workflow.model_dump(mode="json"))
            st.subheader("Result view")
            st.json(compilation.view.model_dump(mode="json"))
        if run is not None:
            st.subheader("Execution plan")
            st.json(run.model_dump(mode="json", exclude={"workflow"}))


if __name__ == "__main__":
    main()
