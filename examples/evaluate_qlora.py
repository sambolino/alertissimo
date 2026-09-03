"""Evaluate a saved QLoRA adapter on the fixed 15-example NLP dev set."""

from __future__ import annotations

import argparse
from pathlib import Path

from alertissimo.api import validate_dsl
from evaluate_local_nlp import SYSTEM_PROMPT, _examples


HERE = Path(__file__).resolve().parent
DEFAULT_ADAPTER = HERE.parent / "models" / "alertissimo-qlora"
DEFAULT_OUTPUT = HERE / "nlp_qlora_results.md"


def _generate(model, tokenizer, user_text: str) -> tuple[str, float]:
    import time

    prompt = tokenizer.apply_chat_template(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    started = time.monotonic()
    generated = model.generate(
        **inputs,
        max_new_tokens=256,
        do_sample=False,
        pad_token_id=tokenizer.eos_token_id,
    )
    elapsed = time.monotonic() - started
    new_tokens = generated[0, inputs.input_ids.shape[1] :]
    text = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip()
    return text, elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--base-model", default="Qwen/Qwen3-8B")
    parser.add_argument("--input", type=Path, default=HERE / "nlp_local_dev.jsonl")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    except ImportError as exc:
        raise SystemExit("Install QLoRA dependencies with: pip install -r requirements-qlora.txt") from exc
    if not torch.cuda.is_available():
        raise SystemExit("QLoRA evaluation requires a CUDA GPU.")

    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=dtype,
    )
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, use_fast=True)
    base_model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        quantization_config=quantization,
        device_map="auto",
        dtype=dtype,
    )
    model = PeftModel.from_pretrained(base_model, args.adapter)
    model.eval()

    rows: list[dict[str, object]] = []
    for index, example in enumerate(_examples(args.input), 1):
        print(f"[{index}/15]", flush=True)
        try:
            dsl, seconds = _generate(model, tokenizer, example["request"])
            validation = validate_dsl(dsl, name=f"QLoRA dev {index}")
            rows.append(
                {
                    **example,
                    "dsl": dsl,
                    "seconds": seconds,
                    "exact": dsl.rstrip() == example["expected_dsl"].rstrip(),
                    "valid": validation.is_valid,
                    "runnable": validation.is_runnable,
                }
            )
        except Exception as exc:  # keep all 15 examples in the report
            rows.append({**example, "error": str(exc)})

    lines = [
        "# QLoRA NLP → DSL evaluation",
        "",
        f"- Adapter: `{args.adapter}`",
        f"- Base model: `{args.base_model}`",
        f"- Development examples: {len(rows)}",
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
