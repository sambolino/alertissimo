"""Streamlit viewer for a light curve stored in a separate JSON file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder


DEFAULT_DATA_PATH = (
    Path(__file__).resolve().parent
    / "plot"
    / "json"
    / "obj-ID-313-lightcurve.json"
)
DEFAULT_IMAGE_PATH = (
    Path(__file__).resolve().parent
    / "plot"
    / "images"
    / "obj-ID-313-lightcurve.png"
)

BAND_COLORS = {
    "g": "#00c853",
    "r": "#ff1744",
    "i": "#ff9100",
    "z": "#d500f9",
}
FALLBACK_COLORS = ["#00b8d4", "#00b85c", "#ff4081", "#651fff"]


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


def month_midpoint_ticks(frame: pd.DataFrame) -> list[object]:
    """Return one centered tick for every month covered by the observations."""
    first_date = frame["date"].min()
    last_date = frame["date"].max()
    first_month = pd.Timestamp(
        year=first_date.year,
        month=first_date.month,
        day=1,
        tz="UTC",
    )
    last_month = pd.Timestamp(
        year=last_date.year,
        month=last_date.month,
        day=1,
        tz="UTC",
    )
    return [
        (month_start + pd.Timedelta(days=14)).to_pydatetime()
        for month_start in pd.date_range(first_month, last_month, freq="MS")
    ]


def lightcurve_chart(
    frame: pd.DataFrame,
    band_counts: dict[str, int] | None = None,
) -> alt.LayerChart:
    """Create the interactive chart used by the Streamlit page."""
    if band_counts is None:
        band_counts = frame["band"].astype(str).value_counts().to_dict()
    count_label_expr = "datum.label"
    for band, count in reversed(list(band_counts.items())):
        count_label_expr = (
            f"datum.label === {json.dumps(band)} "
            f"? {json.dumps(f'{band} ({count})')} : ({count_label_expr})"
        )
    color = alt.Color(
        "band:N",
        title="Band",
        scale=band_scale(frame),
        legend=alt.Legend(
            orient="bottom",
            direction="vertical",
            columns=1,
            labelExpr=count_label_expr,
        ),
    )
    month_ticks = month_midpoint_ticks(frame)
    first_date = frame["date"].min().to_pydatetime()
    last_date = frame["date"].max().to_pydatetime()
    x_axis = alt.X(
        "date:T",
        title="Time (UTC)",
        scale=alt.Scale(
            domain=[min(first_date, month_ticks[0]), max(last_date, month_ticks[-1])],
            padding=20,
        ),
        axis=alt.Axis(
            format="%b %Y",
            values=month_ticks,
            labelAngle=0,
            labelAlign="center",
            labelOverlap="greedy",
        ),
    )
    y_axis = alt.Y(
        "magnitude:Q",
        title="sci mag",
        scale=alt.Scale(zero=False, reverse=True, padding=20),
    )

    base = alt.Chart(frame)
    error_bars = base.mark_rule(strokeWidth=1.25).encode(
        x=x_axis,
        y=alt.Y(
            "magnitudeLow:Q",
            scale=alt.Scale(zero=False, reverse=True, padding=20),
        ),
        y2="magnitudeHigh:Q",
        color=color,
    )

    points = base.mark_circle(size=95).encode(
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


def render_lightcurve_table(data: dict[str, Any]) -> None:
    """Render the original light-curve data in a sortable, paginated grid."""
    table = pd.DataFrame(data["lightCurve"])
    st.subheader("Light curve data")

    grid = GridOptionsBuilder.from_dataframe(table)
    grid.configure_default_column(
        sortable=True,
        filter=False,
        resizable=True,
        editable=False,
    )
    grid.configure_columns(
        list(table.columns),
        sortable=True,
        filter=False,
        editable=False,
    )
    grid.configure_column("date", header_name="UTC date", minWidth=190, flex=2)
    grid.configure_column("mjd", header_name="MJD", minWidth=145, flex=1)
    grid.configure_column(
        "band",
        header_name="Band",
        minWidth=90,
        flex=1,
        headerClass="ag-right-aligned-header",
        cellClass="ag-right-aligned-cell",
    )
    grid.configure_column("magnitude", header_name="Magnitude", minWidth=130, flex=1)
    grid.configure_column(
        "magnitudeError",
        header_name="Magnitude error",
        minWidth=160,
        flex=1,
    )
    grid.configure_pagination(
        enabled=True,
        paginationAutoPageSize=False,
        paginationPageSize=25,
    )
    grid.configure_grid_options(paginationPageSizeSelector=[25, 50, 100])

    AgGrid(
        table,
        gridOptions=grid.build(),
        height=500,
        theme="streamlit",
        enable_enterprise_modules=False,
        update_on=[],
        show_search=False,
        show_download_button=False,
        key="lightcurve_table",
    )


def main() -> None:
    st.set_page_config(page_title="Alertissimo Light Curve", page_icon="📈", layout="wide")
    st.markdown(
        """
        <style>
        :root { color-scheme: light; }
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stHeader"],
        [data-testid="stMetric"],
        [data-testid="stExpander"] {
            background-color: #ffffff;
        }
        .stApp, .stApp p, .stApp label,
        .stApp h1, .stApp h2, .stApp h3,
        [data-testid="stCaptionContainer"],
        [data-testid="stMetricLabel"],
        [data-testid="stMetricValue"],
        [data-testid="stExpander"] summary,
        [data-testid="stMarkdownContainer"] {
            color: #172033 !important;
        }
        [data-testid="stCaptionContainer"] *,
        [data-testid="stMetricLabel"] *,
        [data-testid="stMetricValue"] *,
        [data-testid="stExpander"] summary * {
            color: inherit !important;
        }
        .filter-title {
            color: #172033;
            font-size: 1.25rem !important;
            font-weight: 700 !important;
            margin-bottom: 0.1rem;
        }
        .st-key-band_filter button {
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
        .st-key-band_filter [data-baseweb="button-group"] button:nth-of-type(1) {
            --band-color: #00c853;
            --band-soft-color: #e4f8ea;
            --band-text-color: #007a32;
            --band-active-text-color: #072b15;
        }
        .st-key-band_filter [data-baseweb="button-group"] button:nth-of-type(2) {
            --band-color: #ff1744;
            --band-soft-color: #ffe5ea;
            --band-text-color: #b80028;
            --band-active-text-color: #ffffff;
        }
        .st-key-band_filter [data-baseweb="button-group"] button:nth-of-type(3) {
            --band-color: #ff9100;
            --band-soft-color: #fff1dc;
            --band-text-color: #945400;
            --band-active-text-color: #3b2200;
        }
        .st-key-band_filter [data-baseweb="button-group"] button:nth-of-type(4) {
            --band-color: #d500f9;
            --band-soft-color: #f8e0fb;
            --band-text-color: #850098;
            --band-active-text-color: #ffffff;
        }
        .st-key-band_filter [data-baseweb="button-group"] button {
            background-color: var(--band-soft-color) !important;
            border: 2px solid var(--band-color) !important;
        }
        .st-key-band_filter [data-baseweb="button-group"] button * {
            color: var(--band-text-color) !important;
        }
        .st-key-band_filter [data-baseweb="button-group"] button[kind="pillsActive"] {
            background-color: var(--band-color) !important;
        }
        .st-key-band_filter [data-baseweb="button-group"] button[kind="pillsActive"] * {
            color: var(--band-active-text-color) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Alertissimo Light Curve")
    st.caption("Time versus sci mag")

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

    image_col, chart_col = st.columns([1, 5], gap="large")
    with image_col:
        st.image(
            DEFAULT_IMAGE_PATH,
            caption="Object image",
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
            key="band_filter",
            label_visibility="collapsed",
        )
        filtered_frame = frame[frame["band"].astype(str).isin(selected_bands)]
        if filtered_frame.empty:
            st.info("Select at least one band to display the light curve.")
        else:
            st.altair_chart(
                lightcurve_chart(filtered_frame, band_counts),
                use_container_width=True,
            )
    st.caption(
        "The Y axis is inverted according to astronomical convention: "
        "a lower magnitude means a brighter source."
    )

    if rejected_count:
        st.warning(f"Skipped {rejected_count} invalid measurement(s).")

    render_lightcurve_table(data)

    with st.expander("Object metadata"):
        metadata = {key: value for key, value in data.items() if key != "lightCurve"}
        st.json(metadata)


if __name__ == "__main__":
    main()
