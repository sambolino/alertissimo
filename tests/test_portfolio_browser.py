from tools.portfolio_browser import render_portfolio_html


def test_browser_renders_content_and_escapes_values():
    page = render_portfolio_html({
        "internal_portfolio_id": "portfolio:test",
        "executions": [{"broker": "lasair", "origin": "ztf", "endpoint": "object", "status": "success", "params": {}, "method": "GET", "url": "https://example.invalid"}],
        "records": [{"internal_record_id": "record:1", "semantic_type": "summary@ztf:lasair", "internal_source": None, "fields": {"identity.object_id": "<script>alert(1)</script>"}}],
        "edges": [],
    })
    for expected in ("portfolio:test", "summary@ztf:lasair", "identity.object_id", "lasair / ztf / object", "No edges"):
        assert expected in page
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
