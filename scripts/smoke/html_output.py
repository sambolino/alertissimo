"""Safe multi-Portfolio HTML output for orchestration smoke runs."""

from __future__ import annotations

from collections import Counter
import html
from pathlib import Path

from alertissimo.data_layer.presentation import write_portfolio_html


class HtmlOutputError(ValueError):
    """Raised when a requested HTML output directory cannot be used safely."""


def _h(value: object) -> str:
    return html.escape(str(value), quote=True)


def _object_ids(portfolio) -> list[str]:
    return sorted(
        {
            str(record.fields["identity.object_id"])
            for record in portfolio.records
            if record.fields.get("identity.object_id") is not None
        }
    )


def validate_html_output_directory(directory: str | Path) -> Path:
    """Validate an HTML output path without modifying the filesystem."""
    path = Path(directory)
    try:
        if not path.exists():
            return path
        if not path.is_dir():
            raise HtmlOutputError(f"HTML output path is not a directory: {path}")
        if any(path.iterdir()):
            raise HtmlOutputError(
                f"refusing to overwrite nonempty HTML output directory: {path}"
            )
    except OSError as error:
        raise HtmlOutputError(
            f"could not inspect HTML output path: {path}"
        ) from error
    return path


def _prepare_directory(directory: str | Path) -> Path:
    path = validate_html_output_directory(directory)

    if path.exists():
        return path

    try:
        path.mkdir(parents=True)
    except FileExistsError:
        # The path appeared after validation. Inspect it again rather than
        # assuming it is safe.
        return validate_html_output_directory(path)
    except OSError as error:
        raise HtmlOutputError(
            f"could not create HTML output directory: {path}"
        ) from error

    return path


def write_smoke_html(result, directory: str | Path) -> Path:
    """Write one dossier per normalized Portfolio and a provenance-safe index."""
    portfolios = [
        portfolio
        for step in (result.normalized.steps if result.normalized else ())
        for execution in step.executions
        for portfolio in execution.portfolios
    ]
    if not portfolios:
        raise HtmlOutputError(
            "--html-dir requires a successful result with normalized Portfolios"
        )

    # Validate again after execution, even if the CLI already performed
    # preflight validation.
    output_dir = _prepare_directory(directory)

    cards = []
    for step in result.normalized.steps:
        workflow_step = result.workflow.steps[step.step_index]
        requested = list(workflow_step.target.ids)

        for execution_index, execution in enumerate(step.executions):
            for portfolio_index, portfolio in enumerate(execution.portfolios):
                filename = (
                    f"step-{step.step_index:02d}-"
                    f"execution-{execution_index:02d}-"
                    f"portfolio-{portfolio_index:02d}.html"
                )
                dossier_path = output_dir / filename

                try:
                    write_portfolio_html(portfolio, dossier_path)
                except OSError as error:
                    raise HtmlOutputError(
                        f"could not write HTML dossier: {dossier_path}"
                    ) from error

                identities = _object_ids(portfolio)
                identity_html = (
                    ", ".join(_h(item) for item in identities)
                    if identities
                    else (
                        '<strong class="unavailable">identity unavailable</strong>'
                        " (requested IDs are step context only; no target assignment "
                        "is proven)"
                    )
                )

                semantic_counts = Counter(
                    record.semantic_type for record in portfolio.records
                )
                provenance = "<br>".join(
                    f"{_h(p.broker)} / {_h(p.origin)} / {_h(p.endpoint)}"
                    for p in portfolio.executions
                ) or "provenance unavailable"
                counts = ", ".join(
                    f"{_h(name)}: {_h(count)}"
                    for name, count in sorted(semantic_counts.items())
                ) or "none"

                cards.append(
                    "<article><h2>"
                    f"Step {_h(step.step_index)} · {_h(workflow_step.op)}"
                    "</h2><dl>"
                    f"<dt>Execution</dt><dd>{execution_index} · "
                    f"{_h(execution.execution_id)}</dd>"
                    f"<dt>Portfolio</dt><dd>{portfolio_index} · "
                    f"{_h(portfolio.internal_portfolio_id.value)}</dd>"
                    f"<dt>Provenance</dt><dd>{provenance}</dd>"
                    f"<dt>Requested target IDs</dt><dd>"
                    f"{', '.join(_h(x) for x in requested) or 'none'}</dd>"
                    f"<dt>Normalized object IDs</dt><dd>{identity_html}</dd>"
                    f"<dt>Records</dt><dd>{len(portfolio.records)}</dd>"
                    f"<dt>Semantic types</dt><dd>{counts}</dd></dl>"
                    f'<p><a href="{_h(filename)}">'
                    "Open Portfolio dossier</a></p></article>"
                )

    index = output_dir / "index.html"
    try:
        index.write_text(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Alertissimo smoke Portfolios · {_h(result.name)}</title>"
            "<style>"
            "body{max-width:70rem;margin:2rem auto;padding:0 1rem;"
            "font:16px/1.5 system-ui;color:#162235}"
            "article{border:1px solid #d7e0ea;border-radius:.7rem;"
            "padding:1rem;margin:1rem 0}"
            "h1,h2{line-height:1.2}h2{font-size:1.1rem}"
            "dl{display:grid;grid-template-columns:12rem 1fr;gap:.35rem}"
            "dt{font-weight:bold}.unavailable{color:#9a5500}"
            "</style></head><body>"
            f"<h1>Portfolio dossiers</h1>"
            f"<p>Scenario: {_h(result.name)} · "
            f"Workflow: {_h(result.workflow.name)}</p>"
            f"{''.join(cards)}</body></html>",
            encoding="utf-8",
        )
    except OSError as error:
        raise HtmlOutputError(
            f"could not write HTML index: {index}"
        ) from error

    return index
