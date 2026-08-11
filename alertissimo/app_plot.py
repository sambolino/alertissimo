"""Streamlit viewer for a light curve stored in a separate JSON file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st


DEFAULT_DATA_PATH = (
    Path(__file__).resolve().parent
    / "plot"
    / "json"
    / "obj-ID-313-lightcurve.json"
)

BAND_COLORS = {
    "g": "#2878ff",
    "r": "#ed3b47",
    "i": "#e88b19",
    "z": "#7c55c7",
}
FALLBACK_COLORS = ["#0891b2", "#0f766e", "#db2777", "#475569"]


def load_lightcurve_json(source: Path) -> dict[str, Any]:
    """Load a light-curve document from a JSON file."""
    with source.open(encoding="utf-8") as json_file:
        data = json.load(json_file)

    if not isinstance(data, dict):
        raise ValueError("The JSON root must be an object.")
    if not isinstance(data.get("lightCurve"), list):
        raise ValueError("The JSON must contain a 'lightCurve' array.")
    return data


def lightcurve_dataframe(data: dict[str, Any]) -> tuple[pd.DataFrame, int]:
    """Normalize valid measurements and return their frame and rejected count."""
    frame = pd.DataFrame(data["lightCurve"])
    required = {"date", "band", "magnitude"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(
            "Each lightCurve item must provide: " + ", ".join(sorted(required))
        )

    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True)
    frame["magnitude"] = pd.to_numeric(frame["magnitude"], errors="coerce")
    if "magnitudeError" not in frame:
        frame["magnitudeError"] = 0.0
    frame["magnitudeError"] = (
        pd.to_numeric(frame["magnitudeError"], errors="coerce").fillna(0).clip(lower=0)
    )
    frame["band"] = frame["band"].astype("string").fillna("unknown")

    initial_count = len(frame)
    frame = frame.dropna(subset=["date", "magnitude"]).sort_values("date")
    frame["magnitudeLow"] = frame["magnitude"] - frame["magnitudeError"]
    frame["magnitudeHigh"] = frame["magnitude"] + frame["magnitudeError"]
    return frame, initial_count - len(frame)


def band_scale(frame: pd.DataFrame) -> alt.Scale:
    """Build a stable color scale, including bands not present in the demo file."""
    bands = list(dict.fromkeys(frame["band"].astype(str)))
    colors = [
        BAND_COLORS.get(band, FALLBACK_COLORS[index % len(FALLBACK_COLORS)])
        for index, band in enumerate(bands)
    ]
    return alt.Scale(domain=bands, range=colors)


def lightcurve_chart(frame: pd.DataFrame) -> alt.LayerChart:
    """Create the interactive chart used by the Streamlit page."""
    color = alt.Color(
        "band:N",
        title="Filter",
        scale=band_scale(frame),
        legend=alt.Legend(orient="bottom", direction="horizontal"),
    )
    x_axis = alt.X("date:T", title="Time (UTC)")
    y_axis = alt.Y(
        "magnitude:Q",
        title="sci mag",
        scale=alt.Scale(zero=False, reverse=True),
    )

    base = alt.Chart(frame)
    error_bars = base.mark_rule(strokeWidth=1.25).encode(
        x=x_axis,
        y=alt.Y("magnitudeLow:Q", scale=alt.Scale(zero=False, reverse=True)),
        y2="magnitudeHigh:Q",
        color=color,
    )

    points = base.mark_circle(size=95, stroke="white", strokeWidth=1.5).encode(
        x=x_axis,
        y=y_axis,
        color=color,
        tooltip=[
            alt.Tooltip("date:T", title="Time (UTC)", format="%d/%m/%Y %H:%M:%S"),
            alt.Tooltip("magnitude:Q", title="sci mag", format=".2f"),
            alt.Tooltip("magnitudeError:Q", title="Error", format=".2f"),
            alt.Tooltip("band:N", title="Filter"),
        ],
    )

    return (
        alt.layer(error_bars, points)
        .properties(height=520)
        .configure(background="#ffffff")
        .configure_view(fill="#ffffff", stroke=None)
        .configure_axis(
            gridColor="#e7ecf3",
            domainColor="#9ba8bb",
            labelColor="#66758d",
            titleColor="#35445d",
        )
        .interactive()
    )


def format_utc(value: pd.Timestamp) -> str:
    return value.strftime("%d/%m/%Y %H:%M UTC")


def main() -> None:
    st.set_page_config(page_title="Alertissimo Light Curve", page_icon="📈", layout="wide")
    st.markdown(
        """
        <style>
        :root { color-scheme: light; }
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stHeader"],
        [data-testid="stFileUploaderDropzone"],
        [data-testid="stMetric"],
        [data-testid="stExpander"] {
            background-color: #ffffff;
        }
        .stApp, .stApp p, .stApp label,
        .stApp h1, .stApp h2, .stApp h3 {
            color: #172033;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Alertissimo Light Curve")
    st.caption("Time versus sci mag · data loaded from JSON")

    try:
        data = load_lightcurve_json(DEFAULT_DATA_PATH)
        frame, rejected_count = lightcurve_dataframe(data)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        st.error(f"Unable to display the JSON: {error}")
        st.stop()

    if frame.empty:
        st.warning("The JSON contains no valid light-curve measurements.")
        st.stop()

    object_name = data.get("tns", {}).get("name") or data.get("diaObjectId") or "Object"
    object_id = data.get("diaObjectId", "—")
    st.subheader(f"{object_name} — light curve")
    st.caption(f"diaObjectId {object_id}")

    first, last = frame.iloc[0], frame.iloc[-1]
    brightest = frame["magnitude"].min()
    first_col, last_col, brightest_col, count_col = st.columns(4)
    first_col.metric("First measurement", format_utc(first["date"]))
    last_col.metric("Last measurement", format_utc(last["date"]))
    brightest_col.metric("Brightest", f"{brightest:.2f} mag")
    count_col.metric("Displayed points", len(frame))

    st.altair_chart(lightcurve_chart(frame), use_container_width=True)
    st.caption(
        "The Y axis is inverted according to astronomical convention: "
        "a lower magnitude means a brighter source."
    )

    if rejected_count:
        st.warning(f"Skipped {rejected_count} invalid measurement(s).")

    with st.expander("Object metadata"):
        metadata = {key: value for key, value in data.items() if key != "lightCurve"}
        st.json(metadata)


if __name__ == "__main__":
    main()
