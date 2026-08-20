"""Streamlit prototype for starting a transient investigation.

This page deliberately uses local demo candidates. It models the first two ways
an astronomer may begin work: resolving a known object identifier or searching
around sky coordinates. It does not contact a broker or require credentials.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from alertissimo.app_plot import DEFAULT_DATA_PATH, load_lightcurve_json, render_object_dossier


DATA_DIR = Path(__file__).resolve().parent / "plot" / "json"
CANDIDATES_PATH = DATA_DIR / "search_candidates.json"
PRESETS_PATH = DATA_DIR / "search_presets.json"


@st.cache_data
def load_demo_search_data() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load the local candidate catalogue and form defaults for this prototype."""
    with CANDIDATES_PATH.open(encoding="utf-8") as candidate_file:
        candidates = json.load(candidate_file)
    with PRESETS_PATH.open(encoding="utf-8") as preset_file:
        presets = json.load(preset_file)
    if not isinstance(candidates, list) or not all(isinstance(item, dict) for item in candidates):
        raise ValueError("search_candidates.json must contain an array of objects")
    if not isinstance(presets, dict):
        raise ValueError("search_presets.json must contain an object")
    return candidates, presets


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
    """Show the existing app_plot single-object view below a search result."""
    st.divider()
    st.caption(
        f'Selected search result: {candidate["object_id"]} · {candidate["survey"]} · '
        f'{" · ".join(candidate["brokers"])}. The dossier below uses local demo photometry.'
    )
    try:
        data = load_lightcurve_json(DEFAULT_DATA_PATH)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        st.error(f"Unable to load the local object dossier: {error}")
        return
    render_object_dossier(data, widget_key="search_result")


def render_id_lookup(candidates: list[dict[str, Any]], presets: dict[str, Any]) -> None:
    """Render the known-object-ID entry flow."""
    st.subheader("Look up a known object")
    st.write("Use an LSST `diaObjectId` or a ZTF object ID to begin a dossier.")
    with st.form("object-id-lookup"):
        survey = st.selectbox("Survey", ("ZTF", "LSST"), index=("ZTF", "LSST").index(presets["id_lookup"]["survey"]))
        example = presets["id_lookup"]["object_id"]
        object_id = st.text_input("Object ID", value=example, help="Demo IDs are prefilled.")
        submitted = st.form_submit_button("Find candidate", type="primary")
    if submitted:
        candidate = candidate_for_id(candidates, object_id, survey)
        if candidate is None:
            st.session_state.pop("id_lookup_result", None)
            st.warning("No local demo candidate matches that survey and Object ID.")
            st.caption("Try the prefilled example, or use cone search to discover nearby demo candidates.")
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
        matches = cone_candidates(candidates, ra_deg, dec_deg, radius_arcsec)
        st.session_state["cone_search_results"] = matches

    matches = st.session_state.get("cone_search_results")
    if matches is None:
        return
    if not matches:
        st.warning("No local demo candidates fall inside this cone.")
        st.caption("Increase the radius or try RA 150.12000°, Dec 2.21500°, radius 300 arcsec.")
        return
    st.success(f"{len(matches)} local demo candidate(s) found.")
    frame = pd.DataFrame(matches)[[
        "object_id", "survey", "separation_arcsec", "last_detection", "detections",
        "latest_mag", "classification", "probability", "status", "brokers",
    ]].rename(columns={
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
    selected_id = st.selectbox("Inspect a candidate", [candidate["object_id"] for candidate in matches])
    render_selected_candidate(next(candidate for candidate in matches if candidate["object_id"] == selected_id))


def main() -> None:
    st.set_page_config(page_title="Alertissimo · Find a candidate", page_icon="🔭", layout="wide")
    st.title("Start a transient investigation")
    st.caption("Local UI prototype — no broker request is made from this page.")
    try:
        candidates, presets = load_demo_search_data()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        st.error(f"Unable to load local search demo data: {error}")
        st.stop()
    mode = st.radio(
        "How would you like to begin?",
        ("Object ID", "Cone search"),
        horizontal=True,
        label_visibility="collapsed",
    )
    st.divider()
    if mode == "Object ID":
        render_id_lookup(candidates, presets)
    else:
        render_cone_search(candidates, presets)


if __name__ == "__main__":
    main()
