"""Run the separate local-model NLP development set without executing DSL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from alertissimo.api import validate_dsl
from alertissimo.nlp.prompt import NLP_TO_DSL_SYSTEM_PROMPT


HERE = Path(__file__).resolve().parent
DEFAULT_INPUT = HERE / "nlp_local_dev.jsonl"
DEFAULT_OUTPUT = HERE / "nlp_local_dev_results.md"

SYSTEM_PROMPT = NLP_TO_DSL_SYSTEM_PROMPT


def _examples(path: Path) -> list[dict[str, str]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _generate(
    *, host: str, model: str, user_text: str, seed: int = 42
) -> tuple[str, float]:
    body = json.dumps(
        {
            "model": model,
            "stream": False,
            "think": False,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            "options": {"temperature": 0, "seed": seed, "num_predict": 256},
        }
    ).encode("utf-8")
    request = Request(
        host.rstrip("/") + "/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    with urlopen(request, timeout=600) as response:
        payload = json.loads(response.read().decode("utf-8"))
    elapsed = time.monotonic() - started
    text = payload["message"]["content"].strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()[1:-1]
        text = "\n".join(lines).strip()
    return text, elapsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    examples = _examples(args.input)
    for index, example in enumerate(examples, 1):
        print(f"[{index}/{len(examples)}] {example['language']}", flush=True)
        try:
            dsl, elapsed = _generate(
                host=args.host,
                model=args.model,
                user_text=example["request"],
                seed=args.seed,
            )
            validation = validate_dsl(dsl, name=f"local NLP dev {index}")
            rows.append(
                {
                    **example,
                    "dsl": dsl,
                    "seconds": elapsed,
                    "exact": dsl.rstrip() == example["expected_dsl"].rstrip(),
                    "valid": validation.is_valid,
                    "runnable": validation.is_runnable,
                    "error": None,
                }
            )
        except (KeyError, ValueError, URLError, TimeoutError) as exc:
            rows.append({**example, "error": str(exc)})

    lines = [
        "# Local NLP → DSL evaluation",
        "",
        f"- Model: `{args.model}`",
        f"- Seed: `{args.seed}`",
        f"- Development examples: {len(rows)}",
        "- Acceptance examples from `nlp_examples.txt` were not used.",
        "- Generated DSL was validated locally and never executed.",
        "",
        "| Metric | Passed |",
        "|---|---:|",
        f"| Exact DSL | {sum(bool(row.get('exact')) for row in rows)}/{len(rows)} |",
        f"| Valid DSL | {sum(bool(row.get('valid')) for row in rows)}/{len(rows)} |",
        f"| Runnable DSL | {sum(bool(row.get('runnable')) for row in rows)}/{len(rows)} |",
    ]
    for index, row in enumerate(rows, 1):
        lines.extend(("", f"## {index} · {row['language']}", "", f"> {row['request']}", ""))
        if row.get("error"):
            lines.append(f"- error: `{row['error']}`")
            continue
        lines.extend(
            (
                f"- exact: {'yes' if row['exact'] else 'no'}",
                f"- valid: {'yes' if row['valid'] else 'no'}",
                f"- runnable: {'yes' if row['runnable'] else 'no'}",
                f"- latency: {row['seconds']:.2f} s",
                "",
                "```dsl",
                str(row["dsl"]),
                "```",
                "",
                "Expected:",
                "",
                "```dsl",
                str(row["expected_dsl"]),
                "```",
            )
        )
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
