"""Streamlit viewer for a light curve stored in a separate JSON file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder

from alertissimo.ui_portfolios import (
    DEFAULT_PORTFOLIO,
    load_ui_portfolio,
    loaded_photometry_counts,
    portfolio_to_display,
    records_by_family,
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
    "measurement",
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
    if isinstance(data.get("records"), list):
        return portfolio_to_display(data)
    if not isinstance(data.get("lightCurve"), list):
        raise ValueError("The JSON must contain Portfolio records or a 'lightCurve' array.")
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


def filter_photometry_frame(
    frame: pd.DataFrame,
    *,
    bands: list[str],
    brokers: list[str] | None = None,
    min_real_bogus: float | None = None,
    include_missing: bool = False,
) -> pd.DataFrame:
    """Select displayed measurements without modifying Portfolio evidence."""
    keep = frame["band"].astype(str).isin(bands)
    if brokers is not None:
        keep &= frame["broker"].fillna("unknown").astype(str).isin(brokers)
    if min_real_bogus is not None:
        scores = pd.to_numeric(
            frame.get("real_bogus", pd.Series(index=frame.index, dtype=float)),
            errors="coerce",
        )
        quality = scores.ge(min_real_bogus)
        if include_missing:
            quality |= scores.isna()
        keep &= quality
    return frame.loc[keep].copy()


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
    first_date = frame["date"].min().to_pydatetime(warn=False)
    last_date = frame["date"].max().to_pydatetime(warn=False)
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
            *([
                alt.Tooltip("broker:N", title="Broker"),
                alt.Tooltip("origin:N", title="Survey"),
                alt.Tooltip("record_id:N", title="Record"),
                alt.Tooltip("real_bogus:Q", title="Real/bogus", format=".6f"),
            ] if "broker" in frame else []),
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


def render_lightcurve_table(
    data: dict[str, Any], *, key: str = "lightcurve_table", frame: pd.DataFrame | None = None,
) -> None:
    """Render the selected light-curve measurements in a sortable grid."""
    table = pd.DataFrame(data["lightCurve"]) if frame is None else frame
    # ``details`` is the complete SemanticRecord field mapping used by the
    # click interaction; it is intentionally not a grid column because Arrow
    # tables cannot hash nested dictionaries.
    table = table[[column for column in (
        "date", "mjd", "broker", "origin", "endpoint", "band", "magnitude",
        "magnitudeError", "real_bogus", "record_id"
    ) if column in table]]
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
    for column, label in (
        ("broker", "Broker"), ("origin", "Survey"), ("endpoint", "Endpoint"),
        ("real_bogus", "Real/bogus"),
    ):
        if column in table:
            grid.configure_column(column, header_name=label, minWidth=120, flex=1)
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
    record_id = detection.get("record_id")
    record = next((item for item in records_by_family(data, "measurement") if item.get("record_id") == record_id), None)
    if record is not None:
        render_record_evidence(data, record)
        return
    st.caption("Individual `measurement` SemanticRecord selected from the light curve.")
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


def render_record_evidence(data: dict[str, Any], record: dict[str, Any]) -> None:
    """Show the exact normalized fields and their record-linked execution source."""
    st.caption(f"{record['semantic_type']} · {record['record_id']}")
    source = record.get("internal_source")
    execution_id = source.get("internal_execution_id") if isinstance(source, dict) else None
    execution = next((
        item for item in data.get("executions", [])
        if execution_id is not None and item.get("internal_execution_id") == execution_id
    ), None)
    if execution is not None:
        st.caption(
            f"Broker: {execution.get('broker', '—')} · Survey: {execution.get('origin', '—')} · "
            f"Endpoint: {execution.get('endpoint', '—')}"
        )
    st.markdown("**Normalized fields**")
    st.json(record["fields"], expanded=True)
    st.markdown("**Record source and execution provenance**")
    st.json({"internal_source": source, "execution": execution}, expanded=False)


def _rows(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Return an optional JSON list as safe table rows."""
    value = data.get(key, [])
    return value if isinstance(value, list) else []


def arrow_safe_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Make heterogeneous canonical-record fields safe for Streamlit/Arrow tables."""
    frame = pd.DataFrame(rows)
    for column in frame.select_dtypes(include="object"):
        frame[column] = frame[column].map(
            lambda value: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list))
            else str(value) if value is not None else None
        )
    return frame


def semantic_record_index(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Adapt local demo data into SemanticRecord-shaped UI rows.

    The production UI receives normalized ``Portfolio.records`` directly. This
    adapter makes the prototype obey the same portfolio → SemanticRecord
    hierarchy while its fixture remains deliberately lightweight.
    """
    canonical_records = data.get("semantic_records")
    if isinstance(canonical_records, list):
        return [record for record in canonical_records if isinstance(record, dict)]

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
        add("measurement", f"detection:demo:{index}", detection)
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
    render_record_evidence(data, selected)


def summary_table_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Build transient table rows directly from summary SemanticRecord fields."""

    rows = []
    for record in records_by_family(data, "summary"):
        semantic_type = str(record.get("semantic_type", ""))
        qualifier = semantic_type.partition("@")[2]
        survey, separator, broker = qualifier.partition(":")
        fields = record.get("fields")
        if not isinstance(fields, dict):
            fields = {}

        def display(path: str) -> Any:
            value = fields.get(path)
            return "—" if value is None else value

        rows.append(
            {
                "Provider": broker if separator and broker else "—",
                "Survey": survey if separator and survey else "—",
                "Object ID": display("identity.object_id"),
                "RA": display("position.ra"),
                "Dec": display("position.dec"),
                "Reported detections": display("detection_count"),
                "First MJD": display("time.first_mjd"),
                "Last MJD": display("time.last_mjd"),
            }
        )
    return rows


def render_summary_records(data: dict[str, Any]) -> None:
    """Render every provider summary without selecting an authoritative one."""

    st.markdown("#### Provider summaries")
    rows = summary_table_rows(data)
    if not rows:
        st.info("No summary SemanticRecords are present in this portfolio.")
        return
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_overview(data: dict[str, Any], frame: pd.DataFrame) -> None:
    """Render identity, quality, coverage, and decision-relevant object context."""
    coordinates = data.get("coordinates", {})
    quality = data.get("quality", {})
    left, middle = st.columns([1, 1], gap="large")
    with left:
        st.markdown("#### Identity and sky position")
        st.write(f"**Survey:** {data.get('survey', '—')}")
        summaries = records_by_family(data, "summary")
        if len(summaries) == 1:
            st.write(f"**RA / Dec:** {coordinates.get('ra', '—')}°, {coordinates.get('dec', '—')}°")
        elif summaries:
            st.write("**RA / Dec:** provider-specific positions are listed below")
        else:
            st.write("**RA / Dec:** —")
        st.write(f"**TNS type:** {data.get('tns', {}).get('type', 'Unclassified')}")
        st.write(f"**Candidate status:** {data.get('candidateStatus', 'No assessment')}")
    with middle:
        st.markdown("#### Data quality")
        st.write(quality.get("photometryStatus", "No local quality summary."))
        st.write(f"**Alert quality:** {quality.get('alertQuality', '—')}")
        st.write(f"**Last local refresh:** {quality.get('lastUpdated', '—')}")

    render_summary_records(data)

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
    """Use one measurement selection for the plot, table, and inspector."""
    st.markdown("#### Light curve")
    loaded = loaded_photometry_counts(data)
    if loaded:
        st.caption("Loaded photometry by provider: " + " · ".join(
            f"{broker}: {count}" for broker, count in loaded
        ))
        st.caption("Provider records can include the same observation reported by different brokers.")
    st.caption(
        "DSL filters keep candidate objects when their evidence matches; they do not "
        "remove individual detections. The display controls below select measurements "
        "locally, without provider calls. The full evidence remains in Semantic Records."
    )
    st.markdown("##### Display measurements")
    observed_bands = list(dict.fromkeys(frame["band"].astype(str)))
    configured_bands = list(data.get("filters", {}))
    bands = [band for band in configured_bands if band in observed_bands]
    bands.extend(band for band in observed_bands if band not in bands)
    selected_bands = st.pills(
        "Bands", options=bands, default=bands, selection_mode="multi",
        key=f"band_filter_{widget_key}",
    )
    selected_brokers = None
    if "broker" in frame:
        brokers = sorted(frame["broker"].fillna("unknown").astype(str).unique())
        selected_brokers = st.multiselect(
            "Brokers", brokers, default=brokers, key=f"broker_filter_{widget_key}",
        )
    apply_quality = st.checkbox(
        "Apply real/bogus threshold to displayed measurements",
        key=f"quality_filter_{widget_key}",
    )
    threshold = st.number_input(
        "Minimum real/bogus (inclusive)", min_value=0.0, max_value=1.0,
        value=0.999, step=0.001, format="%.6f", disabled=not apply_quality,
        key=f"quality_threshold_{widget_key}",
    )
    include_missing = st.checkbox(
        "Also show measurements with a missing real/bogus score",
        value=False, disabled=not apply_quality, key=f"quality_missing_{widget_key}",
    )
    if apply_quality:
        st.caption(
            "The threshold uses each record's normalized real/bogus value. "
            "A blank value is missing, not zero. Broker scores are not recalibrated."
        )
    filtered_frame = filter_photometry_frame(
        frame, bands=selected_bands, brokers=selected_brokers,
        min_real_bogus=threshold if apply_quality else None,
        include_missing=include_missing,
    )
    filtered_frame["_point_id"] = filtered_frame.index.astype(str)
    st.caption(f"Showing {len(filtered_frame)} of {len(frame)} loaded valid measurements.")
    if "broker" in filtered_frame and not filtered_frame.empty:
        visible_counts = filtered_frame["broker"].fillna("unknown").value_counts().sort_index()
        st.caption("Shown photometry by provider: " + " · ".join(
            f"{broker}: {count}" for broker, count in visible_counts.items()
        ))
    detection_col, upper_col, forced_col, band_col = st.columns(4)
    detection_col.metric("Shown points", len(filtered_frame))
    record_counts = data.get("record_counts", {})
    upper_col.metric("Loaded non-detections", record_counts.get("non_detection", "—"))
    forced_col.metric("Loaded forced photometry", record_counts.get("forced_photometry", "—"))
    band_col.metric("Shown bands", len(filtered_frame["band"].unique()))

    image_col, chart_col = st.columns([1, 5], gap="large")
    with image_col:
        st.image(DEFAULT_IMAGE_PATH, caption="Object image", use_container_width=True)
    with chart_col:
        band_counts = filtered_frame["band"].astype(str).value_counts().to_dict()
        if filtered_frame.empty:
            st.info("No measurements match the display controls. Adjust the bands, brokers, or quality threshold.")
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
    st.caption("Counts and plotted measurements come from normalized semantic records.")
    if rejected_count:
        st.warning(f"Skipped {rejected_count} invalid measurement(s).")
    render_lightcurve_table(data, key=f"lightcurve_table_{widget_key}", frame=filtered_frame)
    visible_ids = set(filtered_frame.get("record_id", ()))
    detections = [
        record for record in records_by_family(data, "measurement")
        if record["record_id"] in visible_ids
    ]
    if detections:
        with st.expander("Inspect shown detection records"):
            by_id = {record["record_id"]: record for record in detections}
            selected_id = st.selectbox(
                "Detection record", list(by_id),
                format_func=lambda record_id: (
                    f"{by_id[record_id]['semantic_type']} · "
                    f"MJD {by_id[record_id]['fields'].get('time.mjd', '—')} · {record_id}"
                ),
                key=f"detection_inspector_{widget_key}",
            )
            render_record_evidence(data, by_id[selected_id])


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
    matches = arrow_safe_dataframe(_rows(context, "crossmatches"))
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
    """Render a rich, single-object scientific portfolio."""
    evidence_label = data.get("evidenceLabel", "frozen broker evidence")
    if not data.get("lightCurve"):
        object_name = data.get("diaObjectId") or "Object"
        st.subheader(f"{object_name} — object portfolio")
        st.caption(f"{evidence_label} · summary-level Portfolio")
        st.info("This cone result contains a summary record only; no light-curve endpoint was captured for this locus.")
        summary, records, provenance = st.tabs(["Summary", "Semantic Records", "Provenance"])
        with summary:
            st.markdown("#### Identity and sky position")
            st.write(f"**Survey:** {data.get('survey', '—')}")
            summaries = records_by_family(data, "summary")
            if len(summaries) == 1:
                coordinates = data.get("coordinates", {})
                st.write(
                    f"**RA / Dec:** {coordinates.get('ra', '—')}°, "
                    f"{coordinates.get('dec', '—')}°"
                )
            elif summaries:
                st.write("**RA / Dec:** provider-specific positions are listed below")
            else:
                st.write("**RA / Dec:** —")
            render_summary_records(data)
        with records:
            render_semantic_record_browser(data, widget_key=widget_key)
        with provenance:
            render_provenance(data)
        return
    frame, rejected_count = lightcurve_dataframe(data)
    if frame.empty:
        st.warning("The JSON contains no valid light-curve measurements.")
        return
    object_name = data.get("tns", {}).get("name") or data.get("diaObjectId") or "Object"
    st.subheader(f"{object_name} — object portfolio")
    st.caption(f'Object ID {data.get("diaObjectId", "—")} · {evidence_label}')
    first, last, brightest, count = st.columns(4)
    first.metric("First measurement", format_utc(frame.iloc[0]["date"]))
    last.metric("Last measurement", format_utc(frame.iloc[-1]["date"]))
    brightest.metric("Brightest", f'{frame["magnitude"].min():.2f} mag')
    count.metric("Loaded points", len(frame))
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
        data = load_lightcurve_document(load_ui_portfolio(DEFAULT_PORTFOLIO))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        st.error(f"Unable to display the JSON: {error}")
        st.stop()
    render_object_portfolio(data)


if __name__ == "__main__":
    main()
