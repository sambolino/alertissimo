"""Streamlit prototype for starting a transient investigation.

This page deliberately uses local demo candidates. It models three ways an
astronomer may begin work: resolving a known object identifier, searching
around sky coordinates, or entering a future DSL expression. It does not
contact a broker or require credentials.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from alertissimo.app_plot import load_lightcurve_document, render_object_portfolio
from alertissimo.ui_portfolios import (
    SEARCH_PORTFOLIOS,
    load_antares_ztf_cone_portfolios,
    load_ui_portfolio,
    portfolio_to_display,
)


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
            title="Continue with DSL",
            context=f'Continue the survey from {candidate["object_id"]}.',
            key="survey_dsl_after_search_result",
        )


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

    matches = st.session_state.get("cone_search_results")
    if matches is None:
        return
    if not matches:
        st.warning("No frozen fixture candidates fall inside this cone.")
        st.caption("Increase the radius or use the prefilled coordinates.")
        return
    st.success(f"{len(matches)} fixture candidate(s) found.")
    frame = pd.DataFrame(matches)[[
        "object_id", "survey", "separation_arcsec", "last_detection", "detections",
        "latest_mag", "classification", "probability", "status", "brokers",
    ]]
    frame["brokers"] = frame["brokers"].map(
        lambda brokers: " · ".join(map(str, brokers)) if isinstance(brokers, list) else str(brokers)
    )
    frame = frame.rename(columns={
        "object_id": "Object ID", "survey": "Survey", "separation_arcsec": "Separation (arcsec)",
        "last_detection": "Last detection", "detections": "Detections", "latest_mag": "Latest mag",
        "classification": "Leading class", "probability": "Probability", "status": "Behaviour",
        "brokers": "Broker evidence",
    })
    st.dataframe(
        frame,
        use_container_width=True,
        hide_index=True,
        column_config={"Probability": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.0%")},
    )
    selected_id = st.selectbox(
        "Inspect a candidate",
        [candidate.get("candidate_id", candidate["object_id"]) for candidate in matches],
        format_func=lambda candidate_id: next(
            f'{candidate["object_id"]} · {candidate.get("candidate_id", candidate["object_id"])}'
            for candidate in matches if candidate.get("candidate_id", candidate["object_id"]) == candidate_id
        ),
    )
    render_selected_candidate(next(
        candidate for candidate in matches
        if candidate.get("candidate_id", candidate["object_id"]) == selected_id
    ))


def render_dsl_entry(
    *, title: str = "Start with DSL", context: str | None = None, key: str = "survey_dsl"
) -> None:
    """Render the optional DSL entry point without interpreting its contents yet."""
    st.subheader(title)
    st.write("Describe the survey in the Alertissimo DSL. Support for running DSL will be added later.")
    if context:
        st.caption(context)
    dsl_text = st.text_area(
        "DSL",
        placeholder="Enter a DSL survey definition…",
        height=180,
        key=key,
        help="Optional. This prototype stores the text locally for the current session only.",
    )
    if dsl_text:
        st.caption("DSL input is saved for this session. It is not parsed or executed yet.")


def main() -> None:
    st.set_page_config(page_title="Alertissimo · Find a candidate", page_icon="🔭", layout="wide")
    st.title("Start a transient investigation")
    st.caption("Local UI prototype — rendered from frozen broker evidence; no broker request is made.")
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
        render_dsl_entry()


if __name__ == "__main__":
    main()
