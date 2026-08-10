from tools.portfolio_browser import _field_tree, _semantic_type_parts, render_portfolio_html


def test_browser_renders_content_and_escapes_values():
    page = render_portfolio_html({
        "internal_portfolio_id": "portfolio:test",
        "executions": [{"broker": "lasair", "origin": "ztf", "endpoint": "object", "status": "success", "params": {}, "method": "GET", "url": "https://example.invalid"}],
        "records": [{"internal_record_id": "record:1", "semantic_type": "summary@ztf:lasair", "internal_source": {"payload_key": "candidates", "payload_index": 0}, "fields": {"identity.object_id": "<script>alert(1)</script>", "photometry.g.psf.mag": 18.2}}],
        "edges": [],
    })
    for expected in ("portfolio:test", "summary@ztf:lasair", "identity.object_id", "lasair / ztf / object", "No semantic edges yet", "candidates[0]"):
        assert expected in page
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    for expected in (
        "Alertissimo Portfolio", "Transient dossier", "Records", "Edges", "Provenance",
        "Dot-path data browser", "Expand all", "Collapse all", "Search field paths",
        "photometry", "g", "psf", "mag", "photometry.g.psf.mag",
    ):
        assert expected in page
    assert '<details class="tree-node"' in page


def test_field_tree_nests_dot_path_segments():
    tree = _field_tree({"photometry.g.psf.mag": 18.2})
    assert tree["photometry"]["g"]["psf"]["mag"] == 18.2


def test_semantic_type_parts_are_tolerant():
    assert _semantic_type_parts("detection@ztf:lasair") == {
        "base": "detection", "namespace": "ztf", "producer": "lasair",
    }
    assert _semantic_type_parts("summary") == {
        "base": "summary", "namespace": None, "producer": None,
    }


def test_browser_renders_connection_cards_and_escapes_edge_metadata():
    page = render_portfolio_html({
        "internal_portfolio_id": "portfolio:edges",
        "executions": [],
        "records": [
            {"internal_record_id": "record:d", "semantic_type": "detection@ztf:lasair", "fields": {}},
            {"internal_record_id": "record:s", "semantic_type": "summary@ztf:lasair", "fields": {}},
        ],
        "edges": [{
            "internal_edge_id": "edge:1", "edge_type": "--association--",
            "subject_record_id": "record:d", "target_record_id": "record:s",
            "fields": {"basis": "same_execution_summary_context", "note": "<script>alert(1)</script>"},
            "internal_source": None,
        }],
    })
    for expected in (
        "Connection browser", "--association--", "detection@ztf:lasair",
        "summary@ztf:lasair", "same_execution_summary_context", "edge:1",
    ):
        assert expected in page
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
