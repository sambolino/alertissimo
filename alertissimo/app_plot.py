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

SEMANTIC_RECORD_FAMILIES = (
    "summary",
    "detection",
    "crossmatch",
    "lightcurve",
    "spectrum",
    "data_product",
    "classification",
    "survey",
)


def load_lightcurve_json(source: Path) -> dict[str, Any]:
    """Load a light-curve document from a JSON file."""
    with source.open(encoding="utf-8") as json_file:
        data = json.load(json_file)

    return load_lightcurve_document(data)


def load_lightcurve_document(data: Any) -> dict[str, Any]:
    """Validate an in-memory local light-curve document."""

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
    *,
    selection_name: str | None = None,
) -> alt.Chart | alt.LayerChart:
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

    points = base.mark_circle(size=95, cursor="pointer" if selection_name is not None else None).encode(
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

    if selection_name is not None:
        # Streamlit supports selection events only for a single Vega-Lite view,
        # not an Altair layer. Keep this chart clickable; its tooltip and the
        # details panel still expose the photometric uncertainty.
        selection = alt.selection_point(selection_name, fields=["_point_id"], on="click")
        return (
            points.add_params(selection)
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
    return value.strftime("%Y-%m-%d %H:%M UTC")


def render_lightcurve_table(data: dict[str, Any], *, key: str = "lightcurve_table") -> None:
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
        key=key,
    )


def selected_chart_point(event: Any, selection_name: str) -> str | None:
    """Extract a stable point identifier from a Streamlit Altair selection event."""
    if not isinstance(event, dict):
        return None
    selection = event.get("selection", {})
    if not isinstance(selection, dict):
        return None
    points = selection.get(selection_name, [])
    if not isinstance(points, list) or not points or not isinstance(points[0], dict):
        return None
    point_id = points[0].get("_point_id")
    return str(point_id) if point_id is not None else None


def render_detection_details(data: dict[str, Any], detection: pd.Series) -> None:
    """Render the individual detection represented by a selected chart point."""
    st.markdown("#### Detection details")
    st.caption("Individual `detection` SemanticRecord selected from the light curve.")
    details = {
        "time.datetime": format_utc(detection["date"]),
        "time.mjd": float(detection["mjd"]),
        f"photometry.{detection['band']}.psf.mag": float(detection["magnitude"]),
        f"photometry.{detection['band']}.psf.mag.error": float(detection["magnitudeError"]),
        "position.ra": data.get("coordinates", {}).get("ra"),
        "position.dec": data.get("coordinates", {}).get("dec"),
        "provenance.survey": data.get("survey"),
    }
    defaults = data.get("detectionDefaults", {})
    extra = defaults.copy() if isinstance(defaults, dict) else {}
    point_extra = detection.get("details")
    if isinstance(point_extra, dict):
        extra.update(point_extra)
    if isinstance(extra, dict):
        details.update(extra)
    st.json(details, expanded=True)


def _rows(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Return an optional JSON list as safe table rows."""
    value = data.get(key, [])
    return value if isinstance(value, list) else []


def semantic_record_index(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Adapt local demo data into SemanticRecord-shaped UI rows.

    The production UI receives normalized ``Portfolio.records`` directly. This
    adapter makes the prototype obey the same portfolio → SemanticRecord
    hierarchy while its fixture remains deliberately lightweight.
    """
    records: list[dict[str, Any]] = []

    def add(family: str, record_id: str, fields: dict[str, Any]) -> None:
        records.append({
            "record_id": record_id,
            "semantic_type": f"{family}@demo:local",
            "family": family,
            "fields": fields,
        })

    add("summary", "summary:demo:local", {
        "identity.object_id": data.get("diaObjectId"),
        "identity.name": data.get("tns", {}).get("name"),
        "summary": data.get("summary", {}),
    })
    for index, detection in enumerate(_rows(data, "lightCurve"), start=1):
        add("detection", f"detection:demo:{index}", detection)
    if data.get("lightCurve"):
        add("lightcurve", "lightcurve:demo:local", {
            "point_count": len(_rows(data, "lightCurve")),
            "points": _rows(data, "lightCurve"),
        })
    for index, match in enumerate(_rows(data.get("context", {}), "crossmatches"), start=1):
        add("crossmatch", f"crossmatch:demo:{index}", match)
    for index, product in enumerate(_rows(data, "dataProducts"), start=1):
        add("data_product", f"data_product:demo:{index}", product)
    for index, classification in enumerate(_rows(data, "classifications"), start=1):
        add("classification", f"classification:demo:{index}", classification)
    for index, spectrum in enumerate(_rows(data, "spectra"), start=1):
        add("spectrum", f"spectrum:demo:{index}", spectrum)
    for index, coverage in enumerate(_rows(data, "brokerCoverage"), start=1):
        add("survey", f"survey:demo:{index}", coverage)
    return records


def render_semantic_record_browser(data: dict[str, Any], *, widget_key: str) -> None:
    """Render grouped SemanticRecords and allow inspection of one concrete record."""
    records = semantic_record_index(data)
    st.markdown("#### Semantic Records")
    st.caption(
        "A Portfolio collects SemanticRecords. Grouped views show one record family; "
        "select a row below to inspect one concrete record."
    )
    counts = {family: sum(record["family"] == family for record in records) for family in SEMANTIC_RECORD_FAMILIES}
    family = st.selectbox(
        "SemanticRecord family",
        SEMANTIC_RECORD_FAMILIES,
        format_func=lambda value: f"{value} ({counts[value]})",
        key=f"semantic_record_family_{widget_key}",
    )
    grouped = [record for record in records if record["family"] == family]
    if not grouped:
        st.info(f"This portfolio has no {family} SemanticRecords.")
        return

    st.dataframe(
        pd.DataFrame([
            {"Record ID": record["record_id"], "Semantic type": record["semantic_type"]}
            for record in grouped
        ]),
        use_container_width=True,
        hide_index=True,
    )
    selected_id = st.selectbox(
        f"Inspect one {family} SemanticRecord",
        [record["record_id"] for record in grouped],
        key=f"semantic_record_item_{widget_key}",
    )
    selected = next(record for record in grouped if record["record_id"] == selected_id)
    st.markdown(f"**{selected['semantic_type']}** · `{selected['record_id']}`")
    st.json(selected["fields"], expanded=False)


def render_overview(data: dict[str, Any], frame: pd.DataFrame) -> None:
    """Render identity, quality, coverage, and decision-relevant object context."""
    coordinates = data.get("coordinates", {})
    quality = data.get("quality", {})
    left, middle = st.columns([1, 1], gap="large")
    with left:
        st.markdown("#### Identity and sky position")
        st.write(f"**Survey:** {data.get('survey', '—')}")
        st.write(f"**RA / Dec:** {coordinates.get('ra', '—')}°, {coordinates.get('dec', '—')}°")
        st.write(f"**TNS type:** {data.get('tns', {}).get('type', 'Unclassified')}")
        st.write(f"**Candidate status:** {data.get('candidateStatus', 'No assessment')}")
    with middle:
        st.markdown("#### Data quality")
        st.write(quality.get("photometryStatus", "No local quality summary."))
        st.write(f"**Alert quality:** {quality.get('alertQuality', '—')}")
        st.write(f"**Last local refresh:** {quality.get('lastUpdated', '—')}")

    st.markdown("#### Broker coverage")
    coverage = pd.DataFrame(_rows(data, "brokerCoverage"))
    if coverage.empty:
        st.info("No broker coverage is recorded for this local demo object.")
    else:
        coverage["products"] = coverage["products"].apply(lambda value: " · ".join(value))
        st.dataframe(
            coverage.rename(columns={"broker": "Broker", "origin": "Survey", "status": "Status", "products": "Available products"}),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("#### Quick photometry readout")
    summary = data.get("summary", {})
    st.write(
        f"{len(frame)} displayed detection points from {summary.get('firstDetection', '—')} "
        f"to {summary.get('lastDetection', '—')}. Brightest local point: "
        f"{summary.get('brightestMagnitude', '—')} mag."
    )


def render_photometry(data: dict[str, Any], frame: pd.DataFrame, rejected_count: int, widget_key: str) -> None:
    """Render the existing interactive light-curve view and measurement table."""
    st.markdown("#### Light curve")
    detection_col, upper_col, forced_col, band_col = st.columns(4)
    detection_col.metric("Detections", len(frame))
    upper_col.metric("Non-detections", "6 demo")
    forced_col.metric("Forced photometry", "4 demo")
    band_col.metric("Observed bands", len(frame["band"].unique()))

    image_col, chart_col = st.columns([1, 5], gap="large")
    with image_col:
        st.image(DEFAULT_IMAGE_PATH, caption="Object image", use_container_width=True)
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
            key=f"band_filter_{widget_key}",
            label_visibility="collapsed",
        )
        filtered_frame = frame[frame["band"].astype(str).isin(selected_bands)].copy()
        filtered_frame["_point_id"] = filtered_frame.index.astype(str)
        if filtered_frame.empty:
            st.info("Select at least one band to display the light curve.")
        else:
            selection_name = f"detection_point_{widget_key}"
            event = st.altair_chart(
                lightcurve_chart(
                    filtered_frame,
                    band_counts,
                    selection_name=selection_name,
                ),
                use_container_width=True,
                key=f"lightcurve_chart_{widget_key}",
                on_select="rerun",
                selection_mode=selection_name,
            )
            point_id = selected_chart_point(event, selection_name)
            if point_id is not None and point_id in filtered_frame.index.astype(str):
                selected = filtered_frame.loc[filtered_frame.index.astype(str) == point_id].iloc[0]
                render_detection_details(data, selected)
            else:
                st.caption("Click a detection point to inspect its SemanticRecord.")
    st.caption("Magnitude axes are inverted: a lower magnitude means a brighter source.")
    st.caption("Non-detection and forced-photometry counts are local demo metadata; plotted points are detections.")
    if rejected_count:
        st.warning(f"Skipped {rejected_count} invalid measurement(s).")
    render_lightcurve_table(data, key=f"lightcurve_table_{widget_key}")


def render_classification(data: dict[str, Any]) -> None:
    """Render per-broker model outputs without pretending disagreement is resolved."""
    st.markdown("#### Classification evidence")
    classifications = pd.DataFrame(_rows(data, "classifications"))
    if classifications.empty:
        st.info("No classification evidence is available.")
        return
    st.dataframe(
        classifications.rename(columns={"broker": "Broker", "model": "Model", "class": "Class", "probability": "Probability", "computedAt": "Computed at"}),
        use_container_width=True,
        hide_index=True,
        column_config={"Probability": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.0%")},
    )
    st.warning("Demo interpretation: broker classifications are consistent with an extragalactic transient, but they are not identical and should not be merged automatically.")


def render_context(data: dict[str, Any]) -> None:
    """Render host association, catalog context, and solar-system screening."""
    context = data.get("context", {})
    host = context.get("host", {})
    st.markdown("#### Host association")
    first, second, third, fourth = st.columns(4)
    first.metric("Candidate host", host.get("name", "—"))
    second.metric("Host separation", f'{host.get("separationArcsec", "—")} arcsec')
    third.metric("Host redshift", host.get("redshift", "—"))
    probability = host.get("associationProbability")
    fourth.metric("Association probability", f"{probability:.0%}" if isinstance(probability, (int, float)) else "—")
    st.markdown("#### Crossmatches")
    matches = pd.DataFrame(_rows(context, "crossmatches"))
    if not matches.empty:
        st.dataframe(matches.rename(columns={"catalog": "Catalogue", "match": "Result", "separationArcsec": "Separation (arcsec)"}), use_container_width=True, hide_index=True)
    solar_system = context.get("solarSystem", {})
    st.info(f'**Solar-system screen:** {solar_system.get("status", "—")}. Nearest ephemeris separation: {solar_system.get("nearestEphemerisSeparationArcsec", "—")} arcsec.')


def render_images(data: dict[str, Any]) -> None:
    """Render local placeholders for science, template, and difference cutouts."""
    st.markdown("#### Cutout inspection")
    cutouts = _rows(data, "cutouts")
    if not cutouts:
        st.info("No cutouts are listed for this object.")
        return
    columns = st.columns(len(cutouts))
    for column, cutout in zip(columns, cutouts):
        with column:
            st.image(DEFAULT_IMAGE_PATH, caption=f'{cutout.get("kind", "Cutout")} · {cutout.get("band", "—")}')
            st.caption(f'{cutout.get("broker", "—")} · {cutout.get("epoch", "—")} · {cutout.get("status", "—")}')
    st.caption("These are local image placeholders. Production data will render the distinct science, template, and difference products.")


def render_spectra(data: dict[str, Any]) -> None:
    """Render spectrum SemanticRecords, keeping absence distinct from a failed lookup."""
    st.markdown("#### Spectra")
    spectra = pd.DataFrame(_rows(data, "spectra"))
    if spectra.empty:
        st.info("No spectrum SemanticRecords are present in this portfolio.")
        return
    st.dataframe(spectra, use_container_width=True, hide_index=True)


def render_data_products(data: dict[str, Any]) -> None:
    """Render data_product SemanticRecords and related local image products."""
    st.markdown("#### Available data products")
    products = pd.DataFrame(_rows(data, "dataProducts"))
    if not products.empty:
        st.dataframe(products.rename(columns={"product": "Product", "broker": "Broker", "availability": "Availability", "note": "Local demo note"}), use_container_width=True, hide_index=True)


def render_provenance(data: dict[str, Any]) -> None:
    """Render execution provenance for the containing portfolio."""
    st.markdown("#### Broker execution provenance")
    provenance = pd.DataFrame(_rows(data, "provenance"))
    if not provenance.empty:
        st.dataframe(provenance.rename(columns={"broker": "Broker", "endpoint": "Endpoint", "requestedAt": "Requested at", "status": "Status", "records": "Records"}), use_container_width=True, hide_index=True)
    with st.expander("Complete local object metadata"):
        metadata = {key: value for key, value in data.items() if key != "lightCurve"}
        st.json(metadata)


def render_object_portfolio(data: dict[str, Any], *, widget_key: str = "single") -> None:
    """Render a rich, single-object scientific portfolio from local demo data."""
    frame, rejected_count = lightcurve_dataframe(data)
    if frame.empty:
        st.warning("The JSON contains no valid light-curve measurements.")
        return
    object_name = data.get("tns", {}).get("name") or data.get("diaObjectId") or "Object"
    st.subheader(f"{object_name} — object portfolio")
    st.caption(f'diaObjectId {data.get("diaObjectId", "—")} · local demo data')
    first, last, brightest, count = st.columns(4)
    first.metric("First measurement", format_utc(frame.iloc[0]["date"]))
    last.metric("Last measurement", format_utc(frame.iloc[-1]["date"]))
    brightest.metric("Brightest", f'{frame["magnitude"].min():.2f} mag')
    count.metric("Displayed points", len(frame))
    summary, photometry, classification, crossmatches, spectra, products, records, provenance = st.tabs([
        "Summary", "Detections & light curve", "Classifications", "Crossmatches", "Spectra",
        "Data products", "Semantic Records", "Provenance",
    ])
    with summary:
        render_overview(data, frame)
    with photometry:
        st.caption("Hybrid view: this portfolio's lightcurve together with its detection SemanticRecords.")
        render_photometry(data, frame, rejected_count, widget_key)
    with classification:
        render_classification(data)
    with crossmatches:
        render_context(data)
    with spectra:
        render_spectra(data)
    with products:
        render_images(data)
        render_data_products(data)
    with records:
        render_semantic_record_browser(data, widget_key=widget_key)
    with provenance:
        render_provenance(data)


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
        [class*="st-key-band_filter"] button {
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
        [class*="st-key-band_filter"] [data-baseweb="button-group"] button:nth-of-type(1) {
            --band-color: #00c853;
            --band-soft-color: #e4f8ea;
            --band-text-color: #007a32;
            --band-active-text-color: #072b15;
        }
        [class*="st-key-band_filter"] [data-baseweb="button-group"] button:nth-of-type(2) {
            --band-color: #ff1744;
            --band-soft-color: #ffe5ea;
            --band-text-color: #b80028;
            --band-active-text-color: #ffffff;
        }
        [class*="st-key-band_filter"] [data-baseweb="button-group"] button:nth-of-type(3) {
            --band-color: #ff9100;
            --band-soft-color: #fff1dc;
            --band-text-color: #945400;
            --band-active-text-color: #3b2200;
        }
        [class*="st-key-band_filter"] [data-baseweb="button-group"] button:nth-of-type(4) {
            --band-color: #d500f9;
            --band-soft-color: #f8e0fb;
            --band-text-color: #850098;
            --band-active-text-color: #ffffff;
        }
        [class*="st-key-band_filter"] [data-baseweb="button-group"] button {
            background-color: var(--band-soft-color) !important;
            border: 2px solid var(--band-color) !important;
        }
        [class*="st-key-band_filter"] [data-baseweb="button-group"] button * {
            color: var(--band-text-color) !important;
        }
        [class*="st-key-band_filter"] [data-baseweb="button-group"] button[kind="pillsActive"] {
            background-color: var(--band-color) !important;
        }
        [class*="st-key-band_filter"] [data-baseweb="button-group"] button[kind="pillsActive"] * {
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
    except (OSError, json.JSONDecodeError, ValueError) as error:
        st.error(f"Unable to display the JSON: {error}")
        st.stop()
    render_object_portfolio(data)


if __name__ == "__main__":
    main()
