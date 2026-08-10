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
    """Return an HTML-safe display representation."""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    return html.escape(str(value))


def _semantic_type_parts(semantic_type: str) -> dict[str, str | None]:
    """Split a semantic type into its optional badge components."""
    base, separator, qualifier = semantic_type.partition("@")
    namespace: str | None = None
    producer: str | None = None
    if separator:
        namespace_part, producer_separator, producer_part = qualifier.partition(":")
        namespace = namespace_part or None
        if producer_separator:
            producer = producer_part or None
    return {"base": base, "namespace": namespace, "producer": producer}


def _format_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _value_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, (dict, list)):
        return "object"
    return "string"


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


def _render_field_tree(tree: dict[str, Any], prefix: str = "", semantic_type: str = "") -> str:
    """Render a nested field tree with collapsible branches and searchable leaves."""
    parts: list[str] = []
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            parts.append(
                f'<details class="tree-node" open><summary><span class="folder-icon">◇</span>'
                f'<span>{_text(key)}</span><code>{_text(path)}</code></summary>'
                f'<div class="tree-children">{_render_field_tree(value, path, semantic_type)}</div></details>'
            )
        else:
            formatted = _format_value(value)
            searchable = f"{path} {key} {formatted} {semantic_type}".lower()
            kind = _value_kind(value)
            parts.append(
                f'<div class="field-leaf" data-search="{_text(searchable)}">'
                f'<span class="field-key">{_text(key)}</span>'
                f'<span class="full-path">{_text(path)}</span>'
                f'<span class="value value-{kind}">{_text(formatted)}</span></div>'
            )
    return "".join(parts)


def _fields_tree(fields: dict[str, Any], semantic_type: str = "") -> str:
    if not fields:
        return '<p class="empty">No fields.</p>'
    return f'<div class="field-tree">{_render_field_tree(_field_tree(fields), semantic_type=semantic_type)}</div>'


def _source_path(source: Any) -> str:
    if not isinstance(source, dict):
        return "Source not recorded"
    path = source.get("payload_path")
    key = source.get("payload_key")
    index = source.get("payload_index")
    label = str(path) if path not in (None, "", ".") else (str(key) if key else "payload")
    if index is not None:
        label = f"{label}[{index}]"
    return label


def _badges(semantic_type: str) -> str:
    parts = _semantic_type_parts(semantic_type)
    badges = [f'<span class="chip chip-base">{_text(parts["base"])}</span>']
    if parts["namespace"]:
        badges.append(f'<span class="chip chip-namespace">{_text(parts["namespace"])}</span>')
    if parts["producer"]:
        badges.append(f'<span class="chip chip-producer">{_text(parts["producer"])}</span>')
    return "".join(badges)


def _execution_html(item: dict[str, Any], index: int) -> str:
    heading = " / ".join(str(item.get(key) or "—") for key in ("broker", "origin", "endpoint"))
    request = " ".join(str(item.get(key) or "") for key in ("method", "url")).strip() or "Not recorded"
    response_bits = [
        item.get("response_status_code"), item.get("response_content_type"),
        f'{item["raw_size_bytes"]} bytes' if item.get("raw_size_bytes") is not None else None,
    ]
    response = " · ".join(str(value) for value in response_bits if value is not None) or "Not recorded"
    status = str(item.get("status") or "unknown")
    return f'''<details class="execution" {'open' if index == 0 else ''}>
      <summary><span class="provenance-mark">{index + 1:02}</span><span>{_text(heading)}</span><span class="status status-{_text(status.lower())}">{_text(status)}</span></summary>
      <dl>
        <dt>Execution ID</dt><dd><code>{_text(item.get("internal_execution_id") or "Not recorded")}</code></dd>
        <dt>Parameters</dt><dd><pre>{_text(item.get("params", {}))}</pre></dd>
        <dt>Request</dt><dd class="wrap">{_text(request)}</dd>
        <dt>Response</dt><dd>{_text(response)}</dd>
        <dt>Started</dt><dd>{_text(item.get("started_at") or "Not recorded")}</dd>
        <dt>Elapsed</dt><dd>{_text(item.get("elapsed_ms") if item.get("elapsed_ms") is not None else "Not recorded")}</dd>
      </dl></details>'''


def render_portfolio_html(portfolio: dict[str, Any]) -> str:
    """Render a portfolio JSON object, escaping every data-derived value."""
    executions = portfolio.get("executions", []) or []
    records = portfolio.get("records", []) or []
    edges = portfolio.get("edges", []) or []
    portfolio_id = portfolio.get("internal_portfolio_id") or "Unnamed portfolio"

    execution_html = "".join(_execution_html(item, index) for index, item in enumerate(executions))
    execution_html = execution_html or '<div class="empty-state"><strong>No executions.</strong><span>Provenance will appear here when available.</span></div>'

    navigation: dict[str, list[str]] = {}
    record_cards: dict[str, list[str]] = {}
    bases: list[str] = []
    for index, item in enumerate(records):
        semantic_type = str(item.get("semantic_type") or "unknown")
        parts = _semantic_type_parts(semantic_type)
        if parts["base"] not in bases:
            bases.append(parts["base"] or "unknown")
        base = parts["base"] or "unknown"
        fields = item.get("fields", {}) or {}
        source = _source_path(item.get("internal_source"))
        anchor = f"record-{index + 1}"
        producer = f'<span class="mini-badge">{_text(parts["producer"])}</span>' if parts["producer"] else ""
        navigation.setdefault(base, []).append(f'''<a class="record-link" href="#{anchor}">
          <span><strong>{_text(parts["base"] or "unknown")}</strong>{producer}</span>
          <small>{len(fields)} fields · {_text(source)}</small>
          <code>{_text(semantic_type)}</code></a>''')
        record_cards.setdefault(base, []).append(f'''<article class="semantic-card" id="{anchor}" data-semantic="{_text(semantic_type.lower())}">
          <header class="card-header"><div><p class="eyebrow">Semantic record {index + 1:02}</p><h3>{_text(semantic_type)}</h3></div>{_badges(semantic_type)}</header>
          <div class="record-meta"><span><b>Record ID</b><code>{_text(item.get("internal_record_id") or "Not recorded")}</code></span>
          <span><b>Fields</b><strong>{len(fields)}</strong></span><span class="source"><b>Payload source</b><code>{_text(source)}</code></span></div>
          {_fields_tree(fields, semantic_type)}<p class="record-no-match empty">No matching fields.</p></article>''')

    record_html = "".join(
        f'<details class="record-group" {"open" if base in ("summary", "detection") else ""}>'
        f'<summary>{_text(base)} ({len(record_cards[base])})</summary>'
        f'<div class="record-group-cards">{"".join(record_cards[base])}</div></details>'
        for base in bases
    ) or '<div class="empty-state"><strong>No records.</strong><span>This dossier does not contain semantic records yet.</span></div>'
    nav_html = "".join(
        f'<details class="rail-record-group" {"open" if base in ("summary", "detection") else ""}>'
        f'<summary>{_text(base)} ({len(navigation[base])})</summary>'
        f'{"".join(navigation[base])}</details>'
        for base in bases
    ) or '<p class="rail-empty">No records.</p>'
    type_chips = "".join(f'<span class="chip chip-base">{_text(base)}</span>' for base in bases)
    records_by_id = {str(item.get("internal_record_id")): item for item in records}
    if edges:
        edge_rail: list[str] = []
        edge_cards: list[str] = []
        for edge in edges:
            subject_id = str(edge.get("subject_record_id") or "unknown")
            target_id = str(edge.get("target_record_id") or "unknown")
            subject_record = records_by_id.get(subject_id)
            target_record = records_by_id.get(target_id)
            subject_type = str(subject_record.get("semantic_type") or "unknown") if subject_record else f"{subject_id} (unknown record)"
            target_type = str(target_record.get("semantic_type") or "unknown") if target_record else f"{target_id} (unknown record)"
            subject_base = _semantic_type_parts(subject_type)["base"] if subject_record else subject_type
            target_base = _semantic_type_parts(target_type)["base"] if target_record else target_type
            edge_type = str(edge.get("edge_type") or "unknown")
            edge_rail.append(f'<div class="edge-item"><code>{_text(edge_type)}</code><small>{_text(subject_base)} → {_text(target_base)}</small></div>')
            source = edge.get("internal_source")
            source_html = _text(_source_path(source)) if source else "Not recorded (internal edge)"
            edge_cards.append(f'''<article class="connection-card">
              <div class="connection-flow"><strong>{_text(subject_type)}</strong><code>{_text(edge_type)}</code><strong>{_text(target_type)}</strong></div>
              <dl><dt>Edge ID</dt><dd><code>{_text(edge.get("internal_edge_id") or "Not recorded")}</code></dd>
              <dt>Subject</dt><dd><code>{_text(subject_id)}</code></dd><dt>Target</dt><dd><code>{_text(target_id)}</code></dd>
              <dt>Metadata</dt><dd><pre>{_text(edge.get("fields", {}) or {})}</pre></dd>
              <dt>Source</dt><dd>{source_html}</dd></dl></article>''')
        edges_html = "".join(edge_rail)
        connections_html = "".join(edge_cards)
    else:
        edges_html = '<p class="rail-empty">No explicit edges</p>'
        connections_html = ('<div class="empty-state"><strong>No semantic edges.</strong>'
                            '<span>This portfolio contains related records, but no explicit record-to-record assertions yet.</span>'
                            '<span>Containment is represented by the portfolio itself.</span></div>')

    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portfolio dossier · {_text(portfolio_id)}</title><style>
:root{{--bg:#e9eef5;--panel:#fbfcfe;--ink:#162235;--muted:#66758a;--line:#d7e0ea;--accent:#087da1;--accent-2:#6d5bd0;--success:#18794e;--warning:#b56b09;--navy:#0b1729;--shadow:0 12px 30px rgba(18,35,58,.08)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}code,pre,.value,.full-path{{font-family:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace}}button,input{{font:inherit}}
.hero{{background:radial-gradient(circle at 82% -50%,#164a70 0,transparent 42%),var(--navy);color:#f8fbff;padding:1.3rem clamp(1rem,3vw,3rem);border-bottom:1px solid #29425e}}.hero-inner{{max-width:1600px;margin:auto;display:flex;justify-content:space-between;align-items:flex-end;gap:2rem}}.brand p,.eyebrow{{margin:0 0 .2rem;text-transform:uppercase;letter-spacing:.13em;font-size:.7rem;font-weight:800;color:#6fd7ed}}h1{{font-size:1.45rem;margin:0}}.portfolio-id{{display:block;color:#aebdd0;margin-top:.25rem;overflow-wrap:anywhere}}.hero-meta{{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:.55rem}}.metric{{border-left:1px solid #395068;padding:0 .7rem;color:#aebdd0}}.metric b{{display:block;color:white;font-size:1.05rem}}.chips{{display:flex;align-items:center;flex-wrap:wrap;gap:.3rem}}.hero .chips{{width:100%;justify-content:flex-end;margin-top:.25rem}}
.chip,.mini-badge,.status{{display:inline-flex;align-items:center;border-radius:999px;padding:.18rem .5rem;font-size:.72rem;font-weight:800}}.chip-base{{background:#dff5fa;color:#08657e}}.chip-namespace{{background:#e9e6ff;color:#5542b8}}.chip-producer{{background:#fff0d8;color:#995b08}}.mini-badge{{background:#e8edf4;color:#536479;margin-left:.35rem}}.status{{margin-left:auto;background:#eef1f4;color:#59697c}}.status-success,.status-ok,.status-complete,.status-completed{{background:#dff5e9;color:var(--success)}}
.toolbar{{position:sticky;top:0;z-index:10;background:rgba(244,247,251,.94);backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding:.65rem clamp(1rem,3vw,3rem)}}.toolbar-inner{{max-width:1600px;margin:auto;display:flex;gap:.55rem;align-items:center}}button{{border:1px solid #bdc9d8;border-radius:8px;background:white;color:#26374d;padding:.48rem .75rem;font-weight:700;cursor:pointer;box-shadow:0 1px 2px #1522380d}}button:hover{{border-color:var(--accent);color:var(--accent)}}.search-box{{position:relative;flex:1;max-width:620px}}.search-box span{{position:absolute;left:.75rem;top:.48rem;color:var(--muted)}}input[type=search]{{width:100%;border:1px solid #bdc9d8;border-radius:8px;padding:.5rem .8rem .5rem 2rem;background:white;color:var(--ink)}}.match-toggle{{display:flex;align-items:center;gap:.4rem;color:var(--muted);white-space:nowrap;font-weight:650}}
.dossier{{max-width:1600px;margin:0 auto;display:grid;grid-template-columns:minmax(210px,260px) minmax(430px,1fr) minmax(260px,340px);gap:1rem;padding:1rem clamp(1rem,3vw,3rem) 3rem;align-items:start}}.rail,.provenance{{position:sticky;top:69px;max-height:calc(100vh - 85px);overflow:auto}}.panel,.semantic-card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}}.panel{{padding:1rem;margin-bottom:1rem}}.panel h2,.pane-heading h2{{font-size:.82rem;text-transform:uppercase;letter-spacing:.11em;margin:0 0 .75rem;color:#33465e}}.record-link{{display:block;text-decoration:none;color:var(--ink);padding:.65rem;border:1px solid transparent;border-radius:9px;margin:.25rem 0;background:#f1f5f9}}.record-link:hover{{background:white;border-color:#9bcddb}}.record-link span{{display:flex;align-items:center}}.record-link small,.record-link code{{display:block;color:var(--muted);font-size:.72rem;overflow-wrap:anywhere}}.record-link code{{margin-top:.15rem;color:#3f5e7e}}.rail-empty{{color:var(--muted);font-size:.82rem;margin:.2rem 0}}.edge-item{{display:flex;flex-direction:column;gap:.1rem;color:var(--accent);padding:.35rem 0;border-bottom:1px solid var(--line)}}.edge-item small{{color:var(--muted)}}
.rail-record-group{{margin:.4rem 0}}.rail-record-group>summary,.record-group>summary{{font-weight:800;color:#33465e;padding:.45rem;list-style-position:inside}}.record-group{{margin-bottom:1rem}}.record-group-cards{{padding-top:.35rem}}
.pane-heading{{padding:.3rem .2rem .65rem;display:flex;justify-content:space-between;align-items:end}}.pane-heading h2{{font-size:1rem;margin:0}}.pane-heading p{{margin:0;color:var(--muted)}}.semantic-card{{margin-bottom:1rem;overflow:hidden;scroll-margin-top:85px;transition:opacity .2s}}.semantic-card.no-match{{opacity:.38}}.semantic-card.filtered-out{{display:none}}.card-header{{display:flex;justify-content:space-between;gap:1rem;padding:1rem 1.15rem;background:linear-gradient(120deg,#fbfdff,#f3f7fb);border-bottom:1px solid var(--line)}}.card-header h3{{font-size:1.05rem;margin:0;overflow-wrap:anywhere}}.record-meta{{display:flex;flex-wrap:wrap;gap:.55rem;padding:.7rem 1.15rem;border-bottom:1px solid var(--line);background:white}}.record-meta>span{{display:flex;align-items:center;gap:.4rem;border-right:1px solid var(--line);padding-right:.7rem}}.record-meta b{{color:var(--muted);font-size:.68rem;text-transform:uppercase;letter-spacing:.08em}}.record-meta code{{overflow-wrap:anywhere}}.record-meta .source code{{color:var(--warning);font-weight:750}}
.field-tree{{padding:.8rem 1rem 1.1rem}}details summary{{cursor:pointer}}.tree-node{{margin:.15rem 0;border-left:1px solid #cbd8e5;padding-left:.8rem}}.tree-node>summary{{display:flex;align-items:center;gap:.45rem;list-style:none;min-height:1.9rem;font-weight:750}}.tree-node>summary::-webkit-details-marker{{display:none}}.tree-node>summary:before{{content:"›";color:var(--accent);font-size:1.15rem;transition:transform .15s}}.tree-node[open]>summary:before{{transform:rotate(90deg)}}.tree-node>summary code{{margin-left:auto;color:#91a0b3;font-size:.66rem;font-weight:400}}.folder-icon{{color:var(--accent-2)}}.tree-children{{margin-left:.65rem}}.field-leaf{{display:grid;grid-template-columns:minmax(7rem,.7fr) minmax(9rem,1.25fr) minmax(8rem,1fr);align-items:start;gap:.7rem;padding:.36rem .5rem;border-radius:7px}}.field-leaf:hover{{background:#eef5f9}}.field-key{{font-weight:720}}.full-path{{color:#8b99ab;font-size:.69rem;overflow-wrap:anywhere}}.value{{justify-self:end;max-width:100%;padding:.12rem .42rem;border-radius:5px;background:#edf1f5;color:#283950;text-align:right;overflow-wrap:anywhere;white-space:pre-wrap}}.value-number{{background:#e4f4f8;color:#076782;font-variant-numeric:tabular-nums}}.value-bool{{background:#ece9ff;color:#5542b8}}.value-null{{color:#7b8795;font-style:italic}}.value-string,.value-object{{text-align:left}}.record-no-match{{display:none;margin:1rem}}.semantic-card.no-match .record-no-match{{display:block}}
.provenance-mark{{display:grid;place-items:center;min-width:2rem;height:2rem;border-radius:8px;background:#fff0d8;color:var(--warning);font-family:ui-monospace,monospace}}.execution{{border-top:1px solid var(--line);padding:.65rem 0}}.execution:first-of-type{{border-top:0}}.execution>summary{{display:flex;align-items:center;gap:.55rem;font-weight:750;list-style:none}}.execution>summary::-webkit-details-marker{{display:none}}dl{{display:grid;grid-template-columns:5.5rem minmax(0,1fr);gap:.55rem;margin:.8rem 0 0}}dt{{color:var(--muted);font-size:.72rem;font-weight:750}}dd{{margin:0;min-width:0;overflow-wrap:anywhere}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;background:#f3f5f8;border-radius:7px;padding:.45rem;font-size:.72rem}}.empty,.empty-state{{color:var(--muted)}}.empty-state{{display:flex;flex-direction:column;align-items:center;text-align:center;padding:2rem;border:1px dashed #b9c6d5;border-radius:10px}}.empty-state strong{{color:#43556c}}#no-results{{display:none;margin-bottom:1rem}}#no-results.visible{{display:flex}}
.connections{{margin-top:1.25rem}}.connection-card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);padding:1rem;margin-bottom:1rem}}.connection-flow{{display:grid;grid-template-columns:1fr auto 1fr;gap:1rem;align-items:center;text-align:center;padding:.8rem;background:#f1f5f9;border-radius:9px}}.connection-flow code{{color:var(--accent);font-weight:800}}.connection-card dl{{grid-template-columns:6rem minmax(0,1fr)}}
@media(max-width:1050px){{.dossier{{grid-template-columns:220px minmax(0,1fr)}}.provenance{{position:static;max-height:none;grid-column:1/-1}}}}@media(max-width:720px){{.hero-inner{{align-items:flex-start;flex-direction:column}}.hero-meta,.hero .chips{{justify-content:flex-start}}.toolbar-inner{{flex-wrap:wrap}}.search-box{{order:3;flex-basis:100%;max-width:none}}.dossier{{display:block}}.rail{{position:static;max-height:none}}.record-nav{{display:flex;overflow:auto;gap:.4rem}}.record-link{{min-width:190px}}.field-leaf{{grid-template-columns:minmax(6rem,.6fr) 1fr}}.full-path{{display:none}}.value{{justify-self:stretch}}.tree-node>summary code{{display:none}}}}
</style></head><body>
<header class="hero"><div class="hero-inner"><div class="brand"><p>Transient dossier</p><h1>Alertissimo Portfolio</h1><code class="portfolio-id">{_text(portfolio_id)}</code></div><div class="hero-meta">
<span class="metric"><b>{len(records)}</b>records</span><span class="metric"><b>{len(edges)}</b>edges</span><span class="metric"><b>{len(executions)}</b>executions</span><div class="chips">{type_chips}</div></div></div></header>
<nav class="toolbar" aria-label="Field controls"><div class="toolbar-inner"><button type="button" onclick="setExpanded(true)">Expand all</button><button type="button" onclick="setExpanded(false)">Collapse all</button><label class="search-box"><span>⌕</span><input id="path-filter" type="search" placeholder="Search field paths / values" aria-label="Search field paths and values" oninput="filterFields()"></label><label class="match-toggle"><input id="only-matches" type="checkbox" onchange="filterFields()">Show only matched fields</label></div></nav>
<div class="dossier"><aside class="rail"><section class="panel"><h2>Records</h2><div class="record-nav">{nav_html}</div></section><section class="panel"><h2>Edges</h2>{edges_html}</section><section class="panel"><h2>Search</h2><p class="rail-empty">Search paths, leaf keys, values, or semantic types from the toolbar.</p></section></aside>
<main><div class="pane-heading"><div><p>Portfolio dossier</p><h2>Dot-path data browser</h2></div><p>{len(records)} semantic records</p></div><div id="no-results" class="empty-state"><strong>No matching fields.</strong><span>Try a broader path or value.</span></div>{record_html}<section class="connections"><div class="pane-heading"><div><p>Semantic edges</p><h2>Connection browser</h2></div><p>{len(edges)} connections</p></div>{connections_html}</section></main>
<aside class="provenance"><section class="panel"><h2>Provenance</h2>{execution_html}</section></aside></div>
<script>
function setExpanded(open){{document.querySelectorAll('.tree-node,.execution,.record-group,.rail-record-group').forEach(node=>node.open=open)}}
function filterFields(){{
  const query=document.getElementById('path-filter').value.trim().toLowerCase();
  const only=document.getElementById('only-matches').checked;
  let visibleRecords=0;
  document.querySelectorAll('.semantic-card').forEach(card=>{{
    let matches=0;
    card.querySelectorAll('.field-leaf').forEach(leaf=>{{const hit=!query||leaf.dataset.search.includes(query);leaf.hidden=!hit;if(hit)matches++}});
    Array.from(card.querySelectorAll('.tree-node')).reverse().forEach(node=>{{node.hidden=!!query&&!node.querySelector('.field-leaf:not([hidden])');if(query&&!node.hidden)node.open=true}});
    const semanticHit=!!query&&card.dataset.semantic.includes(query);
    if(semanticHit){{card.querySelectorAll('.field-leaf,.tree-node').forEach(node=>node.hidden=false);matches=1}}
    const missed=!!query&&!matches;card.classList.toggle('no-match',missed);card.classList.toggle('filtered-out',missed&&only);
    if(!missed||!only)visibleRecords++;
  }});
  document.getElementById('no-results').classList.toggle('visible',!!query&&visibleRecords===0);
}}
</script></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("portfolio", nargs="?", type=Path, help="portfolio JSON (default: stdin)")
    parser.add_argument("--out", required=True, type=Path, help="output HTML path")
    args = parser.parse_args()
    source = args.portfolio.read_text(encoding="utf-8") if args.portfolio else sys.stdin.read()
    args.out.write_text(render_portfolio_html(json.loads(source)), encoding="utf-8")


if __name__ == "__main__":
    main()
