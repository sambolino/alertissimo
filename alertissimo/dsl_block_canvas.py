"""Small local Streamlit component for the syntax-highlighted DSL block editor."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import streamlit.components.v1 as components


_CANVAS = components.declare_component(
    "alertissimo_dsl_block_canvas",
    path=str(Path(__file__).parent / "components" / "dsl_block_canvas"),
)


def render_dsl_block_canvas(
    *,
    key: str,
    dsl_text: str,
    origins: Sequence[str],
    brokers_by_origin: Mapping[str, Sequence[str]],
    products: Sequence[str],
    brokers: Sequence[str],
    mode: str = "workflow",
) -> dict[str, Any] | None:
    """Render the block editor in full-workflow or local-filter mode."""
    if mode not in {"workflow", "filter"}:
        raise ValueError("mode must be 'workflow' or 'filter'")
    value = _CANVAS(
        dsl_text=dsl_text,
        origins=list(origins),
        brokers_by_origin={name: list(values) for name, values in brokers_by_origin.items()},
        products=list(products),
        brokers=list(brokers),
        mode=mode,
        default=None,
        key=key,
    )
    return value if isinstance(value, dict) else None
