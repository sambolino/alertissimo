"""Streamlit viewer for multiple normalized Alertissimo Portfolios/object groups."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import pandas as pd
import streamlit as st

from alertissimo.app_plot import inject_page_styles, render_lightcurve
from alertissimo.data_layer.presentation.portfolio_lightcurve import (
    LIGHTCURVE_COLUMNS,
    serialized_portfolio_lightcurve_dataframe,
)


def object_lightcurve_groups(data: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Group a serialized Portfolio's projected records by normalized object ID."""
    frame = serialized_portfolio_lightcurve_dataframe(data)
    record_objects: dict[str, str] = {}
    for record in data.get("records", []):
        if not isinstance(record, dict):
            continue
        fields = record.get("fields", {})
        object_id = fields.get("identity.object_id") if isinstance(fields, dict) else None
        if object_id is not None:
            record_objects[str(record.get("internal_record_id"))] = str(object_id)

    grouped: dict[str, list[pd.DataFrame]] = defaultdict(list)
    fallback = str(data.get("internal_portfolio_id", "Portfolio"))
    for record_id, rows in frame.groupby("record_id", sort=False):
        grouped[record_objects.get(str(record_id), fallback)].append(rows)
    if not grouped:
        return {fallback: pd.DataFrame(columns=LIGHTCURVE_COLUMNS)}
    return {name: pd.concat(parts, ignore_index=True) for name, parts in grouped.items()}


def main() -> None:
    st.set_page_config(page_title="Alertissimo Light Curves", page_icon="📈", layout="wide")
    inject_page_styles()
    st.title("Alertissimo Light Curves")
    uploads = st.file_uploader(
        "Stable serialized Portfolio JSON files", type="json", accept_multiple_files=True
    )
    if not uploads:
        st.info("Upload one or more JSON files produced by portfolio_to_json().")
        return
    rendered = 0
    for portfolio_index, upload in enumerate(uploads):
        try:
            data = json.load(upload)
            if not isinstance(data, dict):
                raise ValueError("Portfolio JSON root must be an object")
            groups = object_lightcurve_groups(data)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            st.warning(f"Unable to read {upload.name}: {error}")
            continue
        for group_index, (name, frame) in enumerate(groups.items()):
            if rendered:
                st.divider()
            render_lightcurve(frame, name, key=f"{portfolio_index}_{group_index}")
            rendered += 1


if __name__ == "__main__":
    main()
