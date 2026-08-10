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


def _field_tree(fields: dict[str, Any]) -> dict[str, Any]:
    """Turn dot-separated field paths into a nested dictionary."""
    tree: dict[str, Any] = {}
    for path, value in fields.items():
        branch = tree
        segments = path.split(".")
        for segment in segments[:-1]:
            branch = branch.setdefault(segment, {})
        branch[segments[-1]] = value
    return tree


def _render_field_tree(tree: dict[str, Any], prefix: str = "") -> str:
    """Render a nested field tree with collapsible branches and searchable leaves."""
    parts: list[str] = []
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            parts.append(
                f'<details class="tree-node" open><summary>{_text(key)}</summary>'
                f'<div class="tree-children">{_render_field_tree(value, path)}</div></details>'
            )
        else:
            searchable = f"{path} {_text(value)}"
            parts.append(
                f'<div class="field-leaf" data-path="{_text(path)}" '
                f'data-search="{_text(searchable).lower()}"><span class="field-key">'
                f'{_text(key)}</span><span class="field-value">{_text(value)}</span>'
                f'<span class="full-path">{_text(path)}</span></div>'
            )
    return "".join(parts)


def _fields_tree(fields: dict[str, Any]) -> str:
    if not fields:
        return '<p class="empty">No fields</p>'
    return f'<div class="field-tree">{_render_field_tree(_field_tree(fields))}</div>'


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
        {_fields_tree(item.get('fields', {}))}</details>"""
        for item in records
    ) or '<p class="empty">No records</p>'
    edge_html = "".join(
        f"<details><summary>{_text(item.get('edge_type'))}</summary>{_fields_tree(item.get('fields', {}))}</details>"
        for item in edges
    ) or '<p class="empty">No edges</p>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Portfolio {_text(portfolio.get('internal_portfolio_id'))}</title><style>
*{{box-sizing:border-box}}body{{font:15px system-ui,sans-serif;margin:0;color:#172033;background:#eef1f5}}header{{background:#14243a;color:white;padding:1.5rem max(1rem,calc((100% - 1100px)/2))}}header h1{{margin:0;color:white}}main{{max-width:1100px;margin:auto;padding:1rem}}h2{{color:#193b6a}}section,.record-card{{background:white;border:1px solid #d8deea;border-radius:12px;padding:1rem;margin:.8rem 0;box-shadow:0 2px 8px #1720330d}}details{{margin:.4rem 0}}summary{{font-weight:700;cursor:pointer}}.toolbar{{position:sticky;top:0;z-index:2;display:flex;gap:.5rem;align-items:center;background:#eef1f5;padding:.7rem 0}}button,input{{font:inherit;border:1px solid #aeb8c8;border-radius:6px;padding:.45rem .7rem;background:white}}input{{flex:1}}dl{{display:grid;grid-template-columns:8rem 1fr;gap:.4rem}}dt{{font-weight:700}}dd{{margin:0}}pre,.field-leaf{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:0}}.counts{{color:#c7d2e2}}.empty{{font-style:italic;color:#657085}}.tree-node{{border-left:1px solid #d8deea;padding-left:.8rem}}.tree-children{{margin-left:.6rem}}.field-leaf{{display:grid;grid-template-columns:minmax(8rem,1fr) minmax(8rem,2fr);gap:.7rem;padding:.35rem .5rem;border-radius:5px}}.field-leaf:hover{{background:#f3f6fa}}.field-key{{font-weight:700}}.field-value{{overflow-wrap:anywhere}}.full-path{{display:none}}.badge{{display:inline-block;background:#dfe9f7;color:#244b78;border-radius:999px;padding:.15rem .5rem;margin-right:.3rem}}
</style></head><body><header><h1>Portfolio summary</h1><p><strong>{_text(portfolio.get('internal_portfolio_id'))}</strong></p>
<p class="counts">{len(records)} records · {len(edges)} edges · {len(executions)} executions</p></header><main>
<div class="toolbar"><button type="button" onclick="setExpanded(true)">Expand all</button><button type="button" onclick="setExpanded(false)">Collapse all</button><input id="path-filter" type="search" placeholder="Filter by path or value" oninput="filterFields(this.value)"></div>
<section><h2>Execution summary</h2>{execution_html}</section><section><h2>Dot-path data browser</h2>{record_html}</section><section><h2>Connection browser</h2>{edge_html}</section></main>
<script>function setExpanded(open){{document.querySelectorAll('details').forEach(d=>d.open=open)}}function filterFields(query){{const q=query.toLowerCase();document.querySelectorAll('.field-leaf').forEach(el=>{{el.hidden=!el.dataset.search.includes(q)}});document.querySelectorAll('.tree-node').forEach(node=>{{node.hidden=q!==''&&!node.querySelector('.field-leaf:not([hidden])')}})}}</script></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("portfolio", nargs="?", type=Path, help="portfolio JSON (default: stdin)")
    parser.add_argument("--out", required=True, type=Path, help="output HTML path")
    args = parser.parse_args()
    source = args.portfolio.read_text(encoding="utf-8") if args.portfolio else sys.stdin.read()
    args.out.write_text(render_portfolio_html(json.loads(source)), encoding="utf-8")


if __name__ == "__main__":
    main()
