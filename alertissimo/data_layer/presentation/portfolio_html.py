"""Self-contained HTML dossier renderer for Alertissimo semantic portfolios."""
from __future__ import annotations

import html
import json
from html.parser import HTMLParser
from urllib.parse import urlparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from alertissimo.data_layer.representations import Portfolio
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict

_CSS = '\n:root{--bg:#e9eef5;--panel:#fbfcfe;--ink:#162235;--muted:#66758a;--line:#d7e0ea;--accent:#087da1;--accent-2:#6d5bd0;--success:#18794e;--warning:#b56b09;--navy:#0b1729;--shadow:0 12px 30px rgba(18,35,58,.08)}\n*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}code,pre,.value,.full-path{font-family:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace}button,input{font:inherit}\n.hero{background:radial-gradient(circle at 82% -50%,#164a70 0,transparent 42%),var(--navy);color:#f8fbff;padding:1.3rem clamp(1rem,3vw,3rem);border-bottom:1px solid #29425e}.hero-inner{max-width:1600px;margin:auto;display:flex;justify-content:space-between;align-items:flex-end;gap:2rem}.brand p,.eyebrow{margin:0 0 .2rem;text-transform:uppercase;letter-spacing:.13em;font-size:.7rem;font-weight:800;color:#6fd7ed}h1{font-size:1.45rem;margin:0}.portfolio-id{display:block;color:#aebdd0;margin-top:.25rem;overflow-wrap:anywhere}.hero-meta{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:.55rem}.metric{border-left:1px solid #395068;padding:0 .7rem;color:#aebdd0}.metric b{display:block;color:white;font-size:1.05rem}.chips{display:flex;align-items:center;flex-wrap:wrap;gap:.3rem}.hero .chips{width:100%;justify-content:flex-end;margin-top:.25rem}\n.chip,.mini-badge,.status{display:inline-flex;align-items:center;border-radius:999px;padding:.18rem .5rem;font-size:.72rem;font-weight:800}.chip-base{background:#dff5fa;color:#08657e}.chip-namespace{background:#e9e6ff;color:#5542b8}.chip-producer{background:#fff0d8;color:#995b08}.mini-badge{background:#e8edf4;color:#536479;margin-left:.35rem}.status{margin-left:auto;background:#eef1f4;color:#59697c}.status-success,.status-ok,.status-complete,.status-completed{background:#dff5e9;color:var(--success)}\n.toolbar{position:sticky;top:0;z-index:10;background:rgba(244,247,251,.94);backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding:.65rem clamp(1rem,3vw,3rem)}.toolbar-inner{max-width:1600px;margin:auto;display:flex;gap:.55rem;align-items:center}button{border:1px solid #bdc9d8;border-radius:8px;background:white;color:#26374d;padding:.48rem .75rem;font-weight:700;cursor:pointer;box-shadow:0 1px 2px #1522380d}button:hover{border-color:var(--accent);color:var(--accent)}.search-box{position:relative;flex:1;max-width:620px}.search-box span{position:absolute;left:.75rem;top:.48rem;color:var(--muted)}input[type=search]{width:100%;border:1px solid #bdc9d8;border-radius:8px;padding:.5rem .8rem .5rem 2rem;background:white;color:var(--ink)}.match-toggle{display:flex;align-items:center;gap:.4rem;color:var(--muted);white-space:nowrap;font-weight:650}\n.dossier{max-width:1600px;margin:0 auto;display:grid;grid-template-columns:minmax(210px,260px) minmax(430px,1fr) minmax(260px,340px);gap:1rem;padding:1rem clamp(1rem,3vw,3rem) 3rem;align-items:start}.rail,.provenance{position:sticky;top:69px;max-height:calc(100vh - 85px);overflow:auto}.panel,.semantic-card{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}.panel{padding:1rem;margin-bottom:1rem}.panel h2,.pane-heading h2{font-size:.82rem;text-transform:uppercase;letter-spacing:.11em;margin:0 0 .75rem;color:#33465e}.record-link{display:block;text-decoration:none;color:var(--ink);padding:.65rem;border:1px solid transparent;border-radius:9px;margin:.25rem 0;background:#f1f5f9}.record-link:hover{background:white;border-color:#9bcddb}.record-link span{display:flex;align-items:center}.record-link small,.record-link code{display:block;color:var(--muted);font-size:.72rem;overflow-wrap:anywhere}.record-link code{margin-top:.15rem;color:#3f5e7e}.rail-record-group{margin:.4rem 0}.rail-record-group>summary,.record-group>summary{font-weight:800;color:#33465e}.rail-empty{color:var(--muted);font-size:.82rem;margin:.2rem 0}.edge-item{display:flex;flex-direction:column;gap:.1rem;color:var(--accent);padding:.35rem 0;border-bottom:1px solid var(--line)}.edge-item small{color:var(--muted)}\n.pane-heading{padding:.3rem .2rem .65rem;display:flex;justify-content:space-between;align-items:end}.pane-heading h2{font-size:1rem;margin:0}.pane-heading p{margin:0;color:var(--muted)}.record-group{margin-bottom:1rem}.record-group>summary{padding:.55rem .2rem;font-size:1rem}.semantic-card{margin-bottom:1rem;overflow:hidden;scroll-margin-top:85px;transition:opacity .2s}.semantic-card.no-match{opacity:.38}.semantic-card.filtered-out{display:none}.card-header{display:flex;justify-content:space-between;gap:1rem;padding:1rem 1.15rem;background:linear-gradient(120deg,#fbfdff,#f3f7fb);border-bottom:1px solid var(--line)}.card-header h3{font-size:1.05rem;margin:0;overflow-wrap:anywhere}.record-meta{display:flex;flex-wrap:wrap;gap:.55rem;padding:.7rem 1.15rem;border-bottom:1px solid var(--line);background:white}.record-meta>span{display:flex;align-items:center;gap:.4rem;border-right:1px solid var(--line);padding-right:.7rem}.record-meta b{color:var(--muted);font-size:.68rem;text-transform:uppercase;letter-spacing:.08em}.record-meta code{overflow-wrap:anywhere}.record-meta .source code{color:var(--warning);font-weight:750}\n.field-tree{padding:.8rem 1rem 1.1rem}details summary{cursor:pointer}.tree-node{margin:.15rem 0;border-left:1px solid #cbd8e5;padding-left:.8rem}.tree-node>summary{display:flex;align-items:center;gap:.45rem;list-style:none;min-height:1.9rem;font-weight:750}.tree-node>summary::-webkit-details-marker{display:none}.tree-node>summary:before{content:"›";color:var(--accent);font-size:1.15rem;transition:transform .15s}.tree-node[open]>summary:before{transform:rotate(90deg)}.tree-node>summary code{margin-left:auto;color:#91a0b3;font-size:.66rem;font-weight:400}.folder-icon{color:var(--accent-2)}.array-count{color:var(--muted);font-size:.72rem;font-weight:700}.array-node>summary{background:#f7f9fc;border-radius:6px;padding-right:.35rem}.tree-children{margin-left:.65rem}.field-leaf{display:grid;grid-template-columns:minmax(7rem,.7fr) minmax(9rem,1.25fr) minmax(8rem,1fr);align-items:start;gap:.7rem;padding:.36rem .5rem;border-radius:7px}.field-leaf:hover{background:#eef5f9}.field-key{font-weight:720}.full-path{color:#8b99ab;font-size:.69rem;overflow-wrap:anywhere}.value{justify-self:end;max-width:100%;padding:.12rem .42rem;border-radius:5px;background:#edf1f5;color:#283950;text-align:right;overflow-wrap:anywhere;white-space:pre-wrap}.value-number{background:#e4f4f8;color:#076782;font-variant-numeric:tabular-nums}.value-bool{background:#ece9ff;color:#5542b8}.value-null{color:#7b8795;font-style:italic}.value-string,.value-object{text-align:left}.record-no-match{display:none;margin:1rem}.semantic-card.no-match .record-no-match{display:block}\n.provenance-mark{display:grid;place-items:center;min-width:2rem;height:2rem;border-radius:8px;background:#fff0d8;color:var(--warning);font-family:ui-monospace,monospace}.execution{border-top:1px solid var(--line);padding:.65rem 0}.execution:first-of-type{border-top:0}.execution>summary{display:flex;align-items:center;gap:.55rem;font-weight:750;list-style:none}.execution>summary::-webkit-details-marker{display:none}dl{display:grid;grid-template-columns:5.5rem minmax(0,1fr);gap:.55rem;margin:.8rem 0 0}dt{color:var(--muted);font-size:.72rem;font-weight:750}dd{margin:0;min-width:0;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;background:#f3f5f8;border-radius:7px;padding:.45rem;font-size:.72rem}.empty,.empty-state{color:var(--muted)}.empty-state{display:flex;flex-direction:column;align-items:center;text-align:center;padding:2rem;border:1px dashed #b9c6d5;border-radius:10px}.empty-state strong{color:#43556c}#no-results{display:none;margin-bottom:1rem}#no-results.visible{display:flex}\n.connections{margin-top:1.25rem}.connection-card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:.75rem;margin-bottom:.75rem}.connection-flow{display:grid;grid-template-columns:1fr auto 1fr;gap:.75rem;align-items:center;text-align:center;padding:.55rem}.endpoint{overflow-wrap:anywhere;font-weight:700}.edge-type{color:var(--accent);font-weight:800;background:#e5f3f7;border-radius:999px;padding:.2rem .55rem}.edge-details{border-top:1px solid var(--line);margin-top:.5rem;padding-top:.4rem}.edge-details>summary{color:var(--muted);font-size:.75rem;font-weight:750}.connection-card dl{grid-template-columns:6rem minmax(0,1fr)}\n@media(max-width:1050px){.dossier{grid-template-columns:220px minmax(0,1fr)}.provenance{position:static;max-height:none;grid-column:1/-1}}@media(max-width:720px){.hero-inner{align-items:flex-start;flex-direction:column}.hero-meta,.hero .chips{justify-content:flex-start}.toolbar-inner{flex-wrap:wrap}.search-box{order:3;flex-basis:100%;max-width:none}.dossier{display:block}.rail{position:static;max-height:none}.record-nav{display:flex;overflow:auto;gap:.4rem}.record-link{min-width:190px}.field-leaf{grid-template-columns:minmax(6rem,.6fr) 1fr}.full-path{display:none}.value{justify-self:stretch}.tree-node>summary code{display:none}}\n'
_JS = "\nfunction setExpanded(open){document.querySelectorAll('.tree-node,.execution,.record-group,.rail-record-group').forEach(node=>node.open=open)}\nfunction filterFields(){\n  const query=document.getElementById('path-filter').value.trim().toLowerCase();\n  const only=document.getElementById('only-matches').checked;\n  let visibleRecords=0;\n  document.querySelectorAll('.semantic-card').forEach(card=>{\n    let matches=0;\n    card.querySelectorAll('.field-leaf').forEach(leaf=>{const hit=!query||leaf.dataset.search.includes(query);leaf.hidden=!hit;if(hit)matches++});\n    Array.from(card.querySelectorAll('.tree-node')).reverse().forEach(node=>{node.hidden=!!query&&!node.querySelector('.field-leaf:not([hidden])');if(query&&!node.hidden)node.open=true});\n    const semanticHit=!!query&&card.dataset.semantic.includes(query);\n    if(semanticHit){card.querySelectorAll('.field-leaf,.tree-node').forEach(node=>node.hidden=false);matches=1}\n    const missed=!!query&&!matches;card.classList.toggle('no-match',missed);card.classList.toggle('filtered-out',missed&&only);\n    if(!missed||!only)visibleRecords++;\n  });\n  document.getElementById('no-results').classList.toggle('visible',!!query&&visibleRecords===0);\n}\n"


def _h(value: Any) -> str:
    return html.escape(str(value), quote=True)


_ALLOWED_DESCRIPTION_TAGS = {
    "a", "b", "br", "code", "em", "i", "li", "ol", "p",
    "strong", "sub", "sup", "ul",
}
_ALLOWED_DESCRIPTION_ATTRIBUTES = {
    "a": {"href", "title"},
}
_SAFE_LINK_SCHEMES = {"", "http", "https", "mailto"}


class _DescriptionHTMLSanitizer(HTMLParser):
    """Preserve a small safe subset of broker-supplied description markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in _ALLOWED_DESCRIPTION_TAGS:
            return
        rendered_attrs = []
        allowed = _ALLOWED_DESCRIPTION_ATTRIBUTES.get(tag, set())
        for name, value in attrs:
            name = name.lower()
            if name not in allowed or value is None:
                continue
            if tag == "a" and name == "href":
                if urlparse(value).scheme.lower() not in _SAFE_LINK_SCHEMES:
                    continue
            rendered_attrs.append(
                f' {name}="{html.escape(value, quote=True)}"'
            )
        self.parts.append(f"<{tag}{''.join(rendered_attrs)}>")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag == "br":
            self.parts.append("<br>")
        elif tag in _ALLOWED_DESCRIPTION_TAGS:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _ALLOWED_DESCRIPTION_TAGS and tag != "br":
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        self.parts.append(html.escape(data))

    def handle_entityref(self, name):
        self.parts.append(f"&{name};")

    def handle_charref(self, name):
        self.parts.append(f"&#{name};")


def _description_html(value: str) -> str:
    sanitizer = _DescriptionHTMLSanitizer()
    sanitizer.feed(value)
    sanitizer.close()
    return "".join(sanitizer.parts)


def _parts(semantic_type: str):
    base, sep, qualifier = semantic_type.partition("@")
    if not sep:
        return base, None, None
    namespace, sep2, producer = qualifier.partition(":")
    return base, namespace or None, producer if sep2 else None


def _value(value: Any):
    if value is None:
        return "null", "null"
    if isinstance(value, bool):
        return ("true" if value else "false"), "bool"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value), "number"
    if isinstance(value, str):
        return value, "string"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), "object"


def _tree(fields: Mapping[str, Any]):
    """Build a display tree while allowing a path to be both value and parent.

    Semantic records can legitimately contain, for example, both ``a.b`` and
    ``a.b.c``.  In that case the node for ``a.b`` stores its direct value under
    ``__value__`` while retaining children.  Input ordering must not matter.
    """
    root: dict[str, Any] = {}
    for path, value in fields.items():
        node = root
        parts = path.split(".")
        for part in parts[:-1]:
            if part not in node:
                node[part] = {}
            elif not isinstance(node[part], dict):
                node[part] = {"__value__": node[part]}
            node = node[part]

        leaf = parts[-1]
        if leaf in node and isinstance(node[leaf], dict):
            node[leaf]["__value__"] = value
        else:
            node[leaf] = value
    return root


def _leaf(key, path, value, semantic):
    text, kind = _value(value)
    search = f"{path} {key} {text} {semantic}".lower()
    rendered = (
        _description_html(text)
        if key == "description" and isinstance(value, str)
        else _h(text)
    )
    return (
        f'<div class="field-leaf" data-search="{_h(search)}">'
        f'<span class="field-key">{_h(key)}</span>'
        f'<span class="full-path">{_h(path)}</span>'
        f'<span class="value value-{kind}">{rendered}</span></div>'
    )


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _render_value(key, path, value, semantic, *, mapping_open=True):
    if isinstance(value, Mapping):
        opened = " open" if mapping_open else ""
        out = [
            f'<details class="tree-node mapping-node"{opened}><summary>'
            '<span class="folder-icon">◇</span>'
            f'<span>{_h(key)}</span><code>{_h(path)}</code></summary>'
            '<div class="tree-children">'
        ]
        if "__value__" in value:
            out.append(_render_value(key, path, value["__value__"], semantic))
        for child_key, child_value in value.items():
            if child_key == "__value__":
                continue
            child_path = f"{path}.{child_key}" if path else str(child_key)
            out.append(
                _render_value(
                    child_key,
                    child_path,
                    child_value,
                    semantic,
                    mapping_open=True,
                )
            )
        out.append("</div></details>")
        return "".join(out)

    if _is_sequence(value):
        out = [
            '<details class="tree-node array-node"><summary>'
            '<span class="folder-icon">▤</span>'
            f'<span>{_h(key)}</span>'
            f'<span class="array-count">[{len(value)}]</span>'
            f'<code>{_h(path)}</code></summary><div class="tree-children">'
        ]
        for index, item in enumerate(value):
            item_key = f"[{index}]"
            item_path = f"{path}[{index}]"
            out.append(
                _render_value(
                    item_key,
                    item_path,
                    item,
                    semantic,
                    mapping_open=False,
                )
            )
        out.append("</div></details>")
        return "".join(out)

    return _leaf(key, path, value, semantic)


def _render_tree(node, prefix, semantic):
    out = []
    for key, value in node.items():
        if key == "__value__":
            continue
        path = f"{prefix}.{key}" if prefix else key
        out.append(_render_value(key, path, value, semantic))
    return "".join(out)


def _source(source):
    if not source:
        return "not recorded"
    payload_key = source.get("payload_key") or "payload"
    payload_path = source.get("payload_path") or "."
    index = source.get("payload_index")
    if index is not None:
        base = payload_path if payload_path not in {".", "[]"} else payload_key
        return f"{base}[{index}]"
    return payload_key if payload_path in {".", "[]"} else payload_path


def _chips(semantic):
    base, namespace, producer = _parts(semantic)
    out = [f'<span class="chip chip-base">{_h(base)}</span>']
    if namespace:
        out.append(f'<span class="chip chip-namespace">{_h(namespace)}</span>')
    if producer:
        out.append(f'<span class="chip chip-producer">{_h(producer)}</span>')
    return "".join(out)


def _record(index, record):
    semantic = record["semantic_type"]
    fields = record.get("fields") or {}
    return (
        f'<article class="semantic-card" id="record-{index}" data-semantic="{_h(semantic.lower())}">'
        '<header class="card-header"><div>'
        f'<p class="eyebrow">Semantic record {index:02d}</p><h3>{_h(semantic)}</h3></div>{_chips(semantic)}</header>'
        '<div class="record-meta">'
        f'<span><b>Record ID</b><code>{_h(record["internal_record_id"])}</code></span>'
        f'<span><b>Fields</b><strong>{len(fields)}</strong></span>'
        f'<span class="source"><b>Payload source</b><code>{_h(_source(record.get("internal_source")))}</code></span>'
        '</div>'
        f'<div class="field-tree">{_render_tree(_tree(fields), "", semantic)}</div>'
        '<p class="record-no-match empty">No matching fields.</p></article>'
    )


def _execution(index, execution):
    status = execution.get("status") or "unknown"
    params = json.dumps(execution.get("params") or {}, indent=2, ensure_ascii=False)
    request = " ".join(x for x in (execution.get("method"), execution.get("url")) if x) or "Not recorded"
    response = []
    if execution.get("response_status_code") is not None:
        response.append(str(execution["response_status_code"]))
    if execution.get("response_content_type"):
        response.append(str(execution["response_content_type"]))
    if execution.get("raw_size_bytes") is not None:
        response.append(f'{execution["raw_size_bytes"]} bytes')
    response_text = " · ".join(response) or "Not recorded"
    elapsed = f'{execution["elapsed_ms"]:.1f} ms' if isinstance(execution.get("elapsed_ms"), (int,float)) else "Not recorded"
    return (
        f'<details class="execution" {"open" if index == 1 else ""}><summary>'
        f'<span class="provenance-mark">{index:02d}</span>'
        f'<span>{_h(execution.get("broker"))} / {_h(execution.get("origin"))} / {_h(execution.get("endpoint"))}</span>'
        f'<span class="status status-{_h(str(status).lower())}">{_h(status)}</span></summary><dl>'
        f'<dt>Execution ID</dt><dd><code>{_h(execution.get("internal_execution_id"))}</code></dd>'
        f'<dt>Parameters</dt><dd><pre>{_h(params)}</pre></dd>'
        f'<dt>Request</dt><dd class="wrap">{_h(request)}</dd>'
        f'<dt>Response</dt><dd>{_h(response_text)}</dd>'
        f'<dt>Started</dt><dd>{_h(execution.get("started_at") or "Not recorded")}</dd>'
        f'<dt>Elapsed</dt><dd>{_h(elapsed)}</dd></dl></details>'
    )


def _edges(edges, lookup):
    if not edges:
        return ('<div class="empty-state"><strong>No semantic edges.</strong>'
                '<span>This portfolio contains related records, but no explicit record-to-record assertions yet.</span>'
                '<span>Containment is represented by the portfolio itself.</span></div>')
    out = []
    for edge in edges:
        subject = lookup.get(edge["subject_record_id"], edge["subject_record_id"])
        target = lookup.get(edge["target_record_id"], edge["target_record_id"])
        details = ""
        if edge.get("fields"):
            details = '<details class="edge-details"><summary>Edge fields</summary><pre>' + _h(json.dumps(edge["fields"], indent=2, ensure_ascii=False)) + '</pre></details>'
        out.append('<div class="connection-card"><div class="connection-flow">'
                   f'<span class="endpoint">{_h(subject)}</span><span class="edge-type">{_h(edge["edge_type"])}</span>'
                   f'<span class="endpoint">{_h(target)}</span></div>{details}</div>')
    return "".join(out)


def portfolio_to_html(portfolio: Portfolio) -> str:
    data = portfolio_to_dict(portfolio)
    records, edges, executions = data["records"], data["edges"], data["executions"]
    groups = defaultdict(list)
    bases = []
    for index, record in enumerate(records, 1):
        base, namespace, producer = _parts(record["semantic_type"])
        groups[base].append((index, record))
        if base not in bases:
            bases.append(base)

    nav, main = [], []
    for group_index, (base, items) in enumerate(groups.items()):
        links, cards = [], []
        for index, record in items:
            _, namespace, producer = _parts(record["semantic_type"])
            badge = producer or namespace
            badge_html = f'<span class="mini-badge">{_h(badge)}</span>' if badge else ""
            links.append(f'<a class="record-link" href="#record-{index}"><span><strong>{_h(base)}</strong>{badge_html}</span>'
                         f'<small>{len(record.get("fields") or {})} fields · {_h(_source(record.get("internal_source")))}</small>'
                         f'<code>{_h(record["semantic_type"])}</code></a>')
            cards.append(_record(index, record))
        opened = ' open' if group_index == 0 or base in {"summary", "detection"} else ''
        nav.append(f'<details class="rail-record-group"{opened}><summary>{_h(base)} ({len(items)})</summary>{"".join(links)}</details>')
        main.append(f'<details class="record-group"{opened}><summary>{_h(base)} ({len(items)})</summary><div class="record-group-cards">{"".join(cards)}</div></details>')

    lookup = {r["internal_record_id"]: r["semantic_type"] for r in records}
    rail_edges = ''.join(
        f'<a class="edge-item" href="#connections"><strong>{_h(e["edge_type"])}</strong><small>{_h(lookup.get(e["subject_record_id"], e["subject_record_id"]))} → {_h(lookup.get(e["target_record_id"], e["target_record_id"]))}</small></a>'
        for e in edges
    ) or '<p class="rail-empty">No explicit edges</p>'
    base_chips = ''.join(f'<span class="chip chip-base">{_h(base)}</span>' for base in bases)
    execution_html = ''.join(_execution(i,e) for i,e in enumerate(executions,1)) or '<p class="rail-empty">No execution provenance</p>'

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portfolio dossier · {_h(data["internal_portfolio_id"])}</title><style>{_CSS}</style></head><body>
<header class="hero"><div class="hero-inner"><div class="brand"><p>Transient dossier</p><h1>Alertissimo Portfolio</h1><code class="portfolio-id">{_h(data["internal_portfolio_id"])}</code></div><div class="hero-meta">
<span class="metric"><b>{len(records)}</b>records</span><span class="metric"><b>{len(edges)}</b>edges</span><span class="metric"><b>{len(executions)}</b>executions</span><div class="chips">{base_chips}</div></div></div></header>
<nav class="toolbar" aria-label="Field controls"><div class="toolbar-inner"><button type="button" onclick="setExpanded(true)">Expand all</button><button type="button" onclick="setExpanded(false)">Collapse all</button><label class="search-box"><span>⌕</span><input id="path-filter" type="search" placeholder="Search field paths / values" aria-label="Search field paths and values" oninput="filterFields()"></label><label class="match-toggle"><input id="only-matches" type="checkbox" onchange="filterFields()">Show only matched fields</label></div></nav>
<div class="dossier"><aside class="rail"><section class="panel"><h2>Records</h2><div class="record-nav">{''.join(nav) or '<p class="rail-empty">No semantic records</p>'}</div></section><section class="panel"><h2>Edges</h2>{rail_edges}</section><section class="panel"><h2>Search</h2><p class="rail-empty">Search paths, leaf keys, values, or semantic types from the toolbar.</p></section></aside>
<main><div class="pane-heading"><div><p>Portfolio dossier</p><h2>Dot-path data browser</h2></div><p>{len(records)} semantic records</p></div><div id="no-results" class="empty-state"><strong>No matching fields.</strong><span>Try a broader path or value.</span></div>{''.join(main) or '<div class="empty-state"><strong>No semantic records.</strong></div>'}
<section class="connections" id="connections"><div class="pane-heading"><div><p>Semantic edges</p><h2>Connection browser</h2></div><p>{len(edges)} connections</p></div>{_edges(edges, lookup)}</section></main>
<aside class="provenance"><section class="panel"><h2>Provenance</h2>{execution_html}</section></aside></div><script>{_JS}</script></body></html>"""


def write_portfolio_html(portfolio: Portfolio, path: str | Path = "/tmp/portfolio.html") -> Path:
    output = Path(path)
    output.write_text(portfolio_to_html(portfolio), encoding="utf-8")
    return output
