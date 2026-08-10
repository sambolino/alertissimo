#!/usr/bin/env python3
"""Render serialized Alertissimo portfolios as self-contained static HTML."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any


def _text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, indent=2, ensure_ascii=False)
    return html.escape(str(value))


def _fields_table(fields: dict[str, Any]) -> str:
    if not fields:
        return '<p class="empty">No fields</p>'
    rows = "".join(
        f"<tr><th>{_text(name)}</th><td><pre>{_text(value)}</pre></td></tr>"
        for name, value in fields.items()
    )
    return f"<table>{rows}</table>"


def render_portfolio_html(portfolio: dict[str, Any]) -> str:
    """Render a portfolio JSON object, escaping every data-derived value."""
    executions = portfolio.get("executions", [])
    records = portfolio.get("records", [])
    edges = portfolio.get("edges", [])
    execution_html = "".join(
        f"""<details open><summary>{_text(item.get('broker'))} / {_text(item.get('origin'))} / {_text(item.get('endpoint'))}</summary>
        <dl><dt>Status</dt><dd>{_text(item.get('status'))}</dd><dt>Params</dt><dd><pre>{_text(item.get('params', {}))}</pre></dd>
        <dt>Request</dt><dd>{_text(item.get('method'))} {_text(item.get('url'))}</dd>
        <dt>Response</dt><dd>{_text(item.get('response_status_code'))}; {_text(item.get('response_content_type'))}; {_text(item.get('raw_size_bytes'))} bytes</dd></dl></details>"""
        for item in executions
    ) or '<p class="empty">No executions</p>'
    record_html = "".join(
        f"""<details open><summary>{_text(item.get('semantic_type'))}</summary>
        <p><strong>ID:</strong> {_text(item.get('internal_record_id'))}</p>
        <p><strong>Source:</strong></p><pre>{_text(item.get('internal_source'))}</pre>
        {_fields_table(item.get('fields', {}))}</details>"""
        for item in records
    ) or '<p class="empty">No records</p>'
    edge_html = "".join(
        f"<details><summary>{_text(item.get('edge_type'))}</summary>{_fields_table(item.get('fields', {}))}</details>"
        for item in edges
    ) or '<p class="empty">No edges</p>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Portfolio {_text(portfolio.get('internal_portfolio_id'))}</title><style>
body{{font:15px system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#172033;background:#f5f7fb}}h1,h2{{color:#193b6a}}section,details{{background:white;border:1px solid #d8deea;border-radius:8px;padding:1rem;margin:.8rem 0}}summary{{font-weight:700;cursor:pointer}}dl{{display:grid;grid-template-columns:8rem 1fr;gap:.4rem}}dt{{font-weight:700}}dd{{margin:0}}table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;vertical-align:top;border-top:1px solid #e1e5ed;padding:.5rem}}th{{width:35%}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:0}}.counts{{color:#526177}}.empty{{font-style:italic;color:#657085}}
</style></head><body><header><h1>Portfolio</h1><p><strong>{_text(portfolio.get('internal_portfolio_id'))}</strong></p>
<p class="counts">{len(records)} records · {len(edges)} edges · {len(executions)} executions</p></header>
<section><h2>Executions</h2>{execution_html}</section><section><h2>Records</h2>{record_html}</section><section><h2>Edges</h2>{edge_html}</section></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("portfolio", nargs="?", type=Path, help="portfolio JSON (default: stdin)")
    parser.add_argument("--out", required=True, type=Path, help="output HTML path")
    args = parser.parse_args()
    source = args.portfolio.read_text(encoding="utf-8") if args.portfolio else sys.stdin.read()
    args.out.write_text(render_portfolio_html(json.loads(source)), encoding="utf-8")


if __name__ == "__main__":
    main()
