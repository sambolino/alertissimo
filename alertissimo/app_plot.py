"""Streamlit light-curve viewer for a normalized Alertissimo Portfolio."""

from __future__ import annotations

import json
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from alertissimo.data_layer.presentation.portfolio_lightcurve import (
    LIGHTCURVE_COLUMNS,
    serialized_portfolio_lightcurve_dataframe,
)

BAND_COLORS = {"g": "#00c853", "r": "#ff1744", "i": "#ff9100", "z": "#d500f9"}
FALLBACK_COLORS = ["#00b8d4", "#00b85c", "#ff4081", "#651fff"]


def band_scale(frame: pd.DataFrame) -> alt.Scale:
    """Build a stable color scale for the bands present in a projected frame."""
    bands = list(dict.fromkeys(frame["band"].astype(str)))
    colors = [
        BAND_COLORS.get(band, FALLBACK_COLORS[index % len(FALLBACK_COLORS)])
        for index, band in enumerate(bands)
    ]
    return alt.Scale(domain=bands, range=colors)


def lightcurve_chart(frame: pd.DataFrame) -> alt.LayerChart:
    """Chart one quantity from the normalized light-curve plotting frame."""
    missing = set(LIGHTCURVE_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError("plotting frame is missing columns: " + ", ".join(sorted(missing)))
    quantities = frame["quantity"].dropna().unique()
    if len(quantities) != 1:
        raise ValueError("lightcurve_chart requires exactly one quantity")
    quantity = str(quantities[0])
    plotted = frame.copy()
    plotted["error_low"] = plotted["value"] - plotted["error"]
    plotted["error_high"] = plotted["value"] + plotted["error"]

    color = alt.Color("band:N", title="Band", scale=band_scale(plotted))
    y_scale = alt.Scale(zero=False, reverse=quantity == "mag", padding=20)
    x = alt.X("mjd:Q", title="Observation time (MJD)", scale=alt.Scale(zero=False))
    base = alt.Chart(plotted)
    error_bars = base.transform_filter("isValid(datum.error)").mark_rule(strokeWidth=1.25).encode(
        x=x,
        y=alt.Y("error_low:Q", title=quantity, scale=y_scale),
        y2="error_high:Q",
        color=color,
    )
    points = base.mark_circle(size=90).encode(
        x=x,
        y=alt.Y("value:Q", title=quantity, scale=y_scale),
        color=color,
        shape=alt.Shape("measurement_kind:N", title="Measurement"),
        tooltip=[
            alt.Tooltip("record_id:N", title="Record"),
            alt.Tooltip("semantic_type:N", title="Semantic type"),
            alt.Tooltip("mjd:Q", title="MJD", format=".6f"),
            alt.Tooltip("band:N", title="Band"),
            alt.Tooltip("measurement_kind:N", title="Measurement"),
            alt.Tooltip("value:Q", title=quantity, format=".5g"),
            alt.Tooltip("error:Q", title="Error", format=".5g"),
        ],
    )
    return (
        alt.layer(error_bars, points)
        .properties(height=520)
        .configure(background="#ffffff")
        .configure_view(fill="#ffffff", stroke=None)
        .interactive()
    )


def object_heading(data: dict[str, Any]) -> str:
    """Derive a heading only from normalized identity fields."""
    for record in data.get("records", []):
        fields = record.get("fields", {}) if isinstance(record, dict) else {}
        for path in ("identity.name", "identity.object_id"):
            if fields.get(path) is not None:
                return str(fields[path])
    return str(data.get("internal_portfolio_id", "Portfolio"))


def inject_page_styles() -> None:
    st.markdown("""
    <style>
    :root { color-scheme: light; }
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] { background: #fff; }
    .stApp, .stApp p, .stApp label, .stApp h1, .stApp h2, .stApp h3 { color: #172033 !important; }
    [class*="st-key-band_filter"] button { border-radius: 999px !important; }
    </style>
    """, unsafe_allow_html=True)


def render_lightcurve(frame: pd.DataFrame, heading: str, *, key: str = "single") -> None:
    """Render controls, chart, and table for a normalized plotting frame."""
    st.subheader(f"{heading} — light curve")
    if frame.empty:
        st.warning("No normalized detection photometry is available.")
        return
    bands = list(dict.fromkeys(frame["band"].astype(str)))
    quantities = list(dict.fromkeys(frame["quantity"].astype(str)))
    kinds = list(dict.fromkeys(frame["measurement_kind"].astype(str)))
    selected_bands = st.pills(
        "Bands", bands, default=bands, selection_mode="multi", key=f"band_filter_{key}"
    )
    control_a, control_b = st.columns(2)
    quantity = control_a.selectbox("Quantity", quantities, key=f"quantity_{key}")
    selected_kinds = control_b.multiselect(
        "Measurement kind", kinds, default=kinds, key=f"kind_{key}"
    )
    filtered = frame[
        frame["band"].astype(str).isin(selected_bands)
        & frame["measurement_kind"].astype(str).isin(selected_kinds)
        & (frame["quantity"] == quantity)
    ]
    if filtered.empty:
        st.info("Select at least one available band and measurement kind.")
    else:
        st.altair_chart(lightcurve_chart(filtered), use_container_width=True, key=f"chart_{key}")
        if quantity == "mag":
            st.caption("The magnitude axis is inverted: lower magnitudes are brighter.")
        else:
            st.caption("The flux axis increases upward.")
    st.subheader("Light curve data")
    st.dataframe(frame, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Alertissimo Light Curve", page_icon="📈", layout="wide")
    inject_page_styles()
    st.title("Alertissimo Light Curve")
    upload = st.file_uploader("Stable serialized Portfolio JSON", type="json")
    if upload is None:
        st.info("Upload JSON produced by portfolio_to_json().")
        return
    try:
        data = json.load(upload)
        if not isinstance(data, dict):
            raise ValueError("Portfolio JSON root must be an object")
        frame = serialized_portfolio_lightcurve_dataframe(data)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        st.error(f"Unable to read Portfolio: {error}")
        return
    render_lightcurve(frame, object_heading(data))
    with st.expander("Normalized Portfolio"):
        st.json(data)


if __name__ == "__main__":
    main()
