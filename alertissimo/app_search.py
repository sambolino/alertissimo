"""Streamlit prototype for starting a transient investigation.

This page models three ways an astronomer may begin work: resolving a known
object identifier, searching around sky coordinates, or executing an
Alertissimo DSL request against broker services. The ID and basic cone-search
views remain local demos; DSL execution is live and uses provider credentials.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from alertissimo.api import execute_dsl
from alertissimo.app_plot import load_lightcurve_document, render_object_portfolio
from alertissimo.data_layer.execution import MissingEndpointCredentialError
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict
from alertissimo.dsl_block_canvas import render_dsl_block_canvas
from alertissimo.dsl import (
    DSLParseError,
    SurfaceCapabilityStatus,
    SurfaceLoweringError,
    compile_surface,
    parse_surface_script,
    validate_surface_capabilities,
)
from alertissimo.dsl.blocks import BlockRequirement, render_block_dsl
from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    build_capability_graph,
)
from alertissimo.orchestration.ir import ConeSearchStep
from alertissimo.orchestration.runtime import WorkflowExecutionError
from alertissimo.ui_portfolios import (
    SEARCH_PORTFOLIOS,
    load_antares_ztf_cone_portfolios,
    load_ui_portfolio,
    portfolio_to_display,
)


# The local Streamlit entry point is often run directly rather than through
# ``alertissimo.app``.  Load repository-local credentials for live provider calls
# without overriding credentials supplied by the deployment environment.
load_dotenv(Path(__file__).parents[1] / ".env", override=False)


@st.cache_data
def load_demo_search_data() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build searchable rows exclusively from frozen, normalized Portfolios."""
    portfolios = load_demo_candidate_portfolios()
    candidates = []
    for object_id, portfolio in portfolios.items():
        points = portfolio["lightCurve"]
        if not points:
            continue
        classes = portfolio["classifications"]
        leading = classes[0] if classes else {}
        brokers = sorted({str(row["broker"]) for row in portfolio["provenance"] if row.get("broker")})
        candidates.append({
            "object_id": object_id, "survey": portfolio["survey"],
            "ra_deg": portfolio["coordinates"]["ra"], "dec_deg": portfolio["coordinates"]["dec"],
            "first_detection": points[0]["date"], "last_detection": points[-1]["date"],
            "detections": len(points), "latest_mag": points[-1]["magnitude"],
            "classification": leading.get("class", "No classification"),
            "probability": leading.get("probability"), "brokers": brokers,
            "status": "Frozen broker evidence",
        })
    candidates = [candidate for candidate in candidates if isinstance(candidate["ra_deg"], (int, float)) and isinstance(candidate["dec_deg"], (int, float))]
    if not candidates:
        raise ValueError("The generated Portfolio fixtures contain no searchable detections")
    first = candidates[0]
    presets = {"id_lookup": {"survey": first["survey"], "object_id": first["object_id"]},
               "cone_search": {"ra_deg": first["ra_deg"], "dec_deg": first["dec_deg"], "radius_arcsec": 300.0}}
    return candidates, presets


@st.cache_data
def load_demo_candidate_portfolios() -> dict[str, dict[str, Any]]:
    """Load real Portfolio fixtures and project them only for the existing layout."""
    portfolios = {}
    for name in SEARCH_PORTFOLIOS:
        display = portfolio_to_display(load_ui_portfolio(name))
        portfolios[display["diaObjectId"]] = display
    return portfolios


@st.cache_data
def load_frozen_cone_candidates() -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Expose every locus in the captured four-result ANTARES cone response."""
    candidates = []
    for raw_portfolio in load_antares_ztf_cone_portfolios():
        display = portfolio_to_display(raw_portfolio)
        summary = next(record["fields"] for record in display["semantic_records"] if record["family"] == "summary")
        locus_id = str(summary["identity.antares_locus_id"])
        candidates.append({
            "candidate_id": locus_id, "object_id": display["diaObjectId"], "survey": "ZTF",
            "ra_deg": display["coordinates"]["ra"], "dec_deg": display["coordinates"]["dec"],
            "first_detection": "—", "last_detection": "—", "detections": 0, "latest_mag": None,
            "classification": "No classification", "probability": None,
            "brokers": ["antares"], "status": "Frozen cone result", "portfolio": display,
        })
    first = candidates[0]
    return candidates, {"ra_deg": first["ra_deg"], "dec_deg": first["dec_deg"], "radius_arcsec": 300.0}


def candidate_for_id(
    candidates: list[dict[str, Any]], object_id: str, survey: str
) -> dict[str, Any] | None:
    """Return a local demo candidate matching an ID and selected survey."""
    normalized = object_id.strip().casefold()
    for candidate in candidates:
        if candidate["survey"] == survey and candidate["object_id"].casefold() == normalized:
            return candidate
    return None


def cone_candidates(
    candidates: list[dict[str, Any]], ra_deg: float, dec_deg: float, radius_arcsec: float
) -> list[dict[str, Any]]:
    """Return demo candidates inside an approximate cone, for UI prototyping."""
    radius_deg = radius_arcsec / 3600
    matches = []
    for candidate in candidates:
        separation = ((candidate["ra_deg"] - ra_deg) ** 2 + (candidate["dec_deg"] - dec_deg) ** 2) ** 0.5
        if separation <= radius_deg:
            matches.append({**candidate, "separation_arcsec": round(separation * 3600, 1)})
    return sorted(matches, key=lambda candidate: candidate["separation_arcsec"])


def render_selected_candidate(candidate: dict[str, Any]) -> None:
    """Show a found candidate's portfolio and its DSL continuation option."""
    st.divider()
    st.caption(
        f'Selected search result: {candidate["object_id"]} · {candidate["survey"]} · '
        f'{" · ".join(candidate["brokers"])}. The portfolio below uses frozen broker evidence.'
    )
    portfolio_tab, dsl_tab = st.tabs(("Portfolio", "DSL"))
    with portfolio_tab:
        try:
            data = load_lightcurve_document(candidate.get("portfolio") or load_demo_candidate_portfolios()[candidate["object_id"]])
        except (KeyError, OSError, json.JSONDecodeError, ValueError) as error:
            st.error(f"Unable to load the local portfolio for this search result: {error}")
        else:
            render_object_portfolio(data, widget_key="search_result")
    with dsl_tab:
        render_dsl_entry(
            load_demo_search_data()[0],
            title="Continue with DSL",
            context=f'Continue the survey from {candidate["object_id"]}.',
            key="survey_dsl_after_search_result",
        )


def candidate_result_key(candidate: dict[str, Any]) -> str:
    """Return the stable key used to open one result from a cone-search page."""
    return str(candidate.get("candidate_id", candidate["object_id"]))


def render_cone_result_cards(
    matches: list[dict[str, Any]], *, selection_state_key: str = "cone_search_selected"
) -> None:
    """Render the cone-search result page and let a card open one object."""
    st.subheader("Cone-search results")
    st.success(f"{len(matches)} object(s) found. Select an object to open its portfolio.")

    for index, candidate in enumerate(matches):
        if index:
            st.divider()
        summary, action = st.columns((5, 1), vertical_alignment="center")
        with summary:
            st.markdown(f"### {candidate['object_id']}")
            st.caption(
                f"{candidate['survey']} · {candidate['separation_arcsec']:.1f} arcsec away · "
                f"{' · '.join(candidate['brokers'])}"
            )
            metrics = st.columns(3)
            metrics[0].metric("Detections", candidate["detections"])
            metrics[1].metric("Latest mag", candidate["latest_mag"] or "—")
            probability = candidate.get("probability")
            metrics[2].metric(
                "Leading class",
                candidate["classification"],
                None if probability is None else f"{probability:.0%}",
            )
        with action:
            if st.button(
                "Open object",
                key=f"open-cone-result-{candidate_result_key(candidate)}",
                type="primary",
                use_container_width=True,
            ):
                st.session_state[selection_state_key] = candidate_result_key(candidate)
                st.rerun()


def render_cone_object_page(
    matches: list[dict[str, Any]],
    selected_key: str,
    *,
    selection_state_key: str = "cone_search_selected",
) -> None:
    """Render the one-object page reached from the cone-search result page."""
    candidate = next(
        (item for item in matches if candidate_result_key(item) == selected_key), None
    )
    if candidate is None:
        st.session_state.pop(selection_state_key, None)
        st.warning("The selected object is no longer in these cone-search results.")
        return
    if st.button(
        "← Back to cone-search results",
        key=f"back-to-cone-results-{selection_state_key}",
    ):
        st.session_state.pop(selection_state_key, None)
        st.rerun()
    render_selected_candidate(candidate)


def render_id_lookup(candidates: list[dict[str, Any]], presets: dict[str, Any]) -> None:
    """Render the known-object-ID entry flow."""
    st.subheader("Look up a known object")
    st.write("Use an LSST `diaObjectId` or a ZTF object ID to begin a portfolio.")
    with st.form("object-id-lookup"):
        survey = st.selectbox("Survey", ("ZTF", "LSST"), index=("ZTF", "LSST").index(presets["id_lookup"]["survey"]))
        example = presets["id_lookup"]["object_id"]
        object_id = st.text_input("Object ID", value=example, help="Demo IDs are prefilled.")
        submitted = st.form_submit_button("Find candidate", type="primary")
    if submitted:
        candidate = candidate_for_id(candidates, object_id, survey)
        if candidate is None:
            st.session_state.pop("id_lookup_result", None)
            st.warning("No frozen fixture matches that survey and Object ID.")
            st.caption("Try the prefilled example, or use cone search to discover nearby fixture candidates.")
            return
        st.session_state["id_lookup_result"] = candidate["object_id"]

    selected_id = st.session_state.get("id_lookup_result")
    if selected_id is None:
        return
    candidate = next((item for item in candidates if item["object_id"] == selected_id), None)
    if candidate is not None:
        render_selected_candidate(candidate)


def render_cone_search(candidates: list[dict[str, Any]], presets: dict[str, Any]) -> None:
    """Render coordinate-based discovery using local demo candidates."""
    st.subheader("Search around sky coordinates")
    st.write("Find candidates within a cone around an RA/Dec position.")
    with st.form("cone-search"):
        left, middle, right = st.columns(3)
        ra_deg = left.number_input("RA (deg)", value=float(presets["cone_search"]["ra_deg"]), format="%.5f")
        dec_deg = middle.number_input("Dec (deg)", value=float(presets["cone_search"]["dec_deg"]), format="%.5f")
        radius_arcsec = right.number_input("Radius (arcsec)", min_value=1.0, value=float(presets["cone_search"]["radius_arcsec"]), step=10.0)
        submitted = st.form_submit_button("Search cone", type="primary")
    if submitted:
        cone_candidates_data, _ = load_frozen_cone_candidates()
        matches = cone_candidates(candidates + cone_candidates_data, ra_deg, dec_deg, radius_arcsec)
        st.session_state["cone_search_results"] = matches
        st.session_state.pop("cone_search_selected", None)

    matches = st.session_state.get("cone_search_results")
    if matches is None:
        return
    if not matches:
        st.warning("No frozen fixture candidates fall inside this cone.")
        st.caption("Increase the radius or use the prefilled coordinates.")
        return
    selected_key = st.session_state.get("cone_search_selected")
    if selected_key is None:
        render_cone_result_cards(matches)
    else:
        render_cone_object_page(matches, str(selected_key))


def compile_dsl_cone_preview(dsl_text: str) -> ConeSearchStep | None:
    """Compile a DSL script and expose its cone selector for the local demo UI.

    The search page intentionally does not plan endpoints or execute providers.
    It may only reuse its frozen cone-result view when the compiled candidate
    operation is a cone search.
    """

    compilation = compile_surface(parse_surface_script(dsl_text))
    candidate_step = compilation.workflow.steps[0]
    return candidate_step if isinstance(candidate_step, ConeSearchStep) else None


@st.cache_resource
def load_block_capability_graph() -> CapabilityGraph:
    """Load the local registry used to constrain the visual DSL blocks."""
    return build_capability_graph()


def block_discovery_brokers(
    graph: CapabilityGraph, origins: tuple[str, ...]
) -> tuple[str, ...]:
    """Return only brokers that can run a spatial summary search for every origin."""
    brokers = sorted({endpoint.broker for endpoint in graph.endpoint_capabilities})
    supported = []
    for broker in brokers:
        surface = parse_surface_script(
            render_block_dsl(
                origins=origins,
                broker=broker,
                ra_deg=0,
                dec_deg=0,
                radius=1,
                radius_unit="arcsec",
            )
        )
        if validate_surface_capabilities(surface, graph=graph).status is SurfaceCapabilityStatus.SUPPORTED:
            supported.append(broker)
    return tuple(supported)


def block_requirement_brokers(
    graph: CapabilityGraph,
    *,
    origins: tuple[str, ...],
    discovery_broker: str,
    product: str,
) -> tuple[str, ...]:
    """Offer a product/broker pair only when the registry supports it."""
    options = []
    for broker in sorted({endpoint.broker for endpoint in graph.endpoint_capabilities}):
        script = render_block_dsl(
            origins=origins,
            broker=discovery_broker,
            ra_deg=0,
            dec_deg=0,
            radius=1,
            radius_unit="arcsec",
            requirements=(BlockRequirement(product=product, broker=broker),),
        )
        surface = parse_surface_script(script)
        report = validate_surface_capabilities(surface, graph=graph)
        if report.status is SurfaceCapabilityStatus.SUPPORTED:
            options.append(broker)
    return tuple(options)


def render_dsl_block_input(*, key: str) -> tuple[str, bool]:
    """Render one syntax-highlighted DSL editor without external value controls."""
    text_state_key = f"{key}_block_dsl"
    submit_state_key = f"{key}_block_last_submit"
    graph = load_block_capability_graph()
    origins = sorted({endpoint.origin for endpoint in graph.endpoint_capabilities})
    brokers_by_origin = {
        origin: block_discovery_brokers(graph, (origin,)) for origin in origins
    }
    products = sorted(
        {
            record.semantic_record_type.partition("@")[0]
            for record in graph.semantic_record_capabilities
            if record.semantic_record_type.partition("@")[0] != "summary"
        }
    )
    brokers = sorted({endpoint.broker for endpoint in graph.endpoint_capabilities})
    event = render_dsl_block_canvas(
        key=f"{key}_block_canvas_component",
        dsl_text=str(st.session_state.get(text_state_key, "")),
        origins=origins,
        brokers_by_origin=brokers_by_origin,
        products=products,
        brokers=brokers,
    )
    if event and event.get("submit") and isinstance(event.get("text"), str):
        nonce = event.get("nonce")
        if nonce != st.session_state.get(submit_state_key):
            st.session_state[submit_state_key] = nonce
            st.session_state[text_state_key] = event["text"]
            return event["text"], True
    dsl_text = str(st.session_state.get(text_state_key, ""))
    return dsl_text, False


def render_dsl_entry(
    candidates: list[dict[str, Any]],
    *,
    title: str = "Start with DSL",
    context: str | None = None,
    key: str = "survey_dsl",
) -> None:
    """Execute DSL against providers and display normalized semantic results."""

    results_state_key = f"{key}_cone_results"
    selection_state_key = f"{key}_cone_selected"
    execution_state_key = f"{key}_dsl_execution"

    st.subheader(title)
    st.write("Describe the survey in the Alertissimo DSL.")
    if context:
        st.caption(context)
    dsl_text, submitted = render_dsl_block_input(key=key)

    if submitted:
        try:
            with st.spinner("Executing DSL against broker services…"):
                execution = execute_dsl(dsl_text, name=f"interactive DSL: {key}")
        except DSLParseError as error:
            st.error(f"DSL syntax error: {error}")
            return
        except SurfaceLoweringError as error:
            st.error(f"DSL cannot be compiled: {error}")
            return
        except MissingEndpointCredentialError as error:
            st.error(f"DSL requires a broker credential: {error}")
            return
        except WorkflowExecutionError as error:
            st.error(f"A broker request failed: {error}")
            return
        except Exception as error:
            st.error(f"Live DSL execution failed: {type(error).__name__}: {error}")
            return

        st.session_state[execution_state_key] = execution
        st.session_state.pop(results_state_key, None)
        st.session_state.pop(selection_state_key, None)

    execution = st.session_state.get(execution_state_key)
    if execution is not None:
        st.success(
            f"Live DSL execution completed: {len(execution.portfolios)} semantic "
            "portfolio(s) returned."
        )
        st.caption(
            "Results are normalized through the provider mappings. Raw broker payloads "
            "are not displayed."
        )
        for index, portfolio in enumerate(execution.portfolios, start=1):
            with st.expander(f"Portfolio {index}", expanded=index == 1):
                st.json(portfolio_to_dict(portfolio))
        return

    matches = st.session_state.get(results_state_key)
    if matches is None:
        return
    st.caption(
        "Frozen cone preview: the compiled `inside (...)` selector is applied to "
        "local broker evidence. Provider execution and non-spatial predicates are "
        "not run on this page."
    )
    if not matches:
        st.warning("No frozen fixture candidates fall inside this DSL cone.")
        return
    selected_key = st.session_state.get(selection_state_key)
    if selected_key is None:
        render_cone_result_cards(matches, selection_state_key=selection_state_key)
    else:
        render_cone_object_page(
            matches,
            str(selected_key),
            selection_state_key=selection_state_key,
        )


def main() -> None:
    st.set_page_config(page_title="Alertissimo · Find a candidate", page_icon="🔭", layout="wide")
    st.title("Start a transient investigation")
    st.caption(
        "ID and cone-search views use frozen broker evidence. DSL runs execute live "
        "provider requests and return normalized semantic portfolios."
    )
    try:
        candidates, presets = load_demo_search_data()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        st.error(f"Unable to load local search demo data: {error}")
        st.stop()
    mode = st.radio(
        "How would you like to begin?",
        ("Object ID", "Cone search", "DSL"),
        horizontal=True,
        label_visibility="collapsed",
    )
    st.divider()
    if mode == "Object ID":
        render_id_lookup(candidates, presets)
    elif mode == "Cone search":
        _, cone_presets = load_frozen_cone_candidates()
        render_cone_search(candidates, {**presets, "cone_search": cone_presets})
    else:
        render_dsl_entry(candidates)


if __name__ == "__main__":
    main()
