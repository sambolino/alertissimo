"""Streamlit viewer for multiple light curves stored in one JSON file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from alertissimo.app_plot import (
    DEFAULT_IMAGE_PATH,
    lightcurve_chart,
    lightcurve_dataframe,
)


DEFAULT_OBJECTS_PATH = (
    Path(__file__).resolve().parent / "plot" / "json" / "objects.json"
)


def load_objects_json(source: Path) -> list[dict[str, Any]]:
    """Load and validate a list of light-curve objects."""
    with source.open(encoding="utf-8") as json_file:
        data = json.load(json_file)

    if not isinstance(data, list):
        raise ValueError("The JSON root must be an array.")
    if not data:
        raise ValueError("The JSON array must contain at least one object.")

    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Item {index} must be an object.")
        if not isinstance(item.get("lightCurve"), list):
            raise ValueError(f"Item {index} must contain a 'lightCurve' array.")
    return data


def inject_page_styles() -> None:
    """Apply the light theme and band colors used by the single-object page."""
    st.markdown(
        """
        <style>
        :root { color-scheme: light; }
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stHeader"] {
            background-color: #ffffff;
        }
        .stApp, .stApp p, .stApp label,
        .stApp h1, .stApp h2, .stApp h3,
        [data-testid="stCaptionContainer"],
        [data-testid="stMarkdownContainer"] {
            color: #172033 !important;
        }
        [data-testid="stCaptionContainer"] * {
            color: inherit !important;
        }
        .filter-title {
            color: #172033;
            font-size: 1.25rem !important;
            font-weight: 700 !important;
            margin-bottom: 0.1rem;
        }
        [class*="st-key-band_filter_"] button {
            width: 2.5rem !important;
            min-width: 2.5rem !important;
            max-width: 2.5rem !important;
            height: 2.5rem !important;
            min-height: 2.5rem !important;
            padding: 0 !important;
            border-radius: 50% !important;
            aspect-ratio: 1 / 1;
            flex: 0 0 2.5rem !important;
        }
        [class*="st-key-band_filter_"] [data-baseweb="button-group"] button:nth-of-type(1) {
            --band-color: #00c853;
            --band-soft-color: #e4f8ea;
            --band-text-color: #007a32;
            --band-active-text-color: #072b15;
        }
        [class*="st-key-band_filter_"] [data-baseweb="button-group"] button:nth-of-type(2) {
            --band-color: #ff1744;
            --band-soft-color: #ffe5ea;
            --band-text-color: #b80028;
            --band-active-text-color: #ffffff;
        }
        [class*="st-key-band_filter_"] [data-baseweb="button-group"] button:nth-of-type(3) {
            --band-color: #ff9100;
            --band-soft-color: #fff1dc;
            --band-text-color: #945400;
            --band-active-text-color: #3b2200;
        }
        [class*="st-key-band_filter_"] [data-baseweb="button-group"] button:nth-of-type(4) {
            --band-color: #d500f9;
            --band-soft-color: #f8e0fb;
            --band-text-color: #850098;
            --band-active-text-color: #ffffff;
        }
        [class*="st-key-band_filter_"] [data-baseweb="button-group"] button {
            background-color: var(--band-soft-color) !important;
            border: 2px solid var(--band-color) !important;
        }
        [class*="st-key-band_filter_"] [data-baseweb="button-group"] button * {
            color: var(--band-text-color) !important;
        }
        [class*="st-key-band_filter_"] [data-baseweb="button-group"] button[kind="pillsActive"] {
            background-color: var(--band-color) !important;
        }
        [class*="st-key-band_filter_"] [data-baseweb="button-group"] button[kind="pillsActive"] * {
            color: var(--band-active-text-color) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_object(data: dict[str, Any], index: int) -> None:
    """Render one object image and its independently filterable light curve."""
    frame, rejected_count = lightcurve_dataframe(data)
    object_name = data.get("tns", {}).get("name") or data.get("diaObjectId") or "Object"
    object_id = data.get("diaObjectId", "—")

    st.subheader(f"{object_name} — light curve")
    st.caption(f"diaObjectId {object_id}")

    if frame.empty:
        st.warning("This object contains no valid light-curve measurements.")
        return

    image_col, chart_col = st.columns([1, 5], gap="large")
    with image_col:
        st.image(
            DEFAULT_IMAGE_PATH,
            caption=f"{object_name} image",
            use_container_width=True,
        )

    with chart_col:
        observed_bands = list(dict.fromkeys(frame["band"].astype(str)))
        configured_bands = list(data.get("filters", {}))
        bands = [band for band in configured_bands if band in observed_bands]
        bands.extend(band for band in observed_bands if band not in bands)
        band_counts = frame["band"].astype(str).value_counts().to_dict()

        st.markdown('<div class="filter-title">Filter</div>', unsafe_allow_html=True)
        selected_bands = st.pills(
            "Filter",
            options=bands,
            default=bands,
            selection_mode="multi",
            key=f"band_filter_{index}",
            label_visibility="collapsed",
        )
        filtered_frame = frame[frame["band"].astype(str).isin(selected_bands)]
        if filtered_frame.empty:
            st.info("Select at least one band to display the light curve.")
        else:
            st.altair_chart(
                lightcurve_chart(filtered_frame, band_counts).properties(height=420),
                use_container_width=True,
                key=f"lightcurve_chart_{index}",
            )

    if rejected_count:
        st.warning(f"Skipped {rejected_count} invalid measurement(s).")


def main() -> None:
    st.set_page_config(
        page_title="Alertissimo Light Curves",
        page_icon="📈",
        layout="wide",
    )
    inject_page_styles()
    st.title("Alertissimo Light Curves")
    st.caption("Multiple objects — time versus sci mag")

    try:
        objects = load_objects_json(DEFAULT_OBJECTS_PATH)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        st.error(f"Unable to display the JSON: {error}")
        st.stop()

    for index, data in enumerate(objects):
        if index:
            st.divider()
        try:
            render_object(data, index)
        except ValueError as error:
            st.warning(f"Unable to display object {index + 1}: {error}")


if __name__ == "__main__":
    main()
