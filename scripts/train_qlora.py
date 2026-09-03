"""Fine-tune a causal chat model on the Alertissimo DSL dataset with QLoRA.

The base model is loaded in 4-bit NF4 and only a LoRA adapter is trained.  The
dataset is split by canonical DSL answer, so paraphrases of the same answer do
not leak from training into evaluation.

Install the optional dependencies from ``requirements-qlora.txt`` before
running this script.  The script intentionally does not add those large GPU
dependencies to the main application requirements.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "dataset" / "nlp_finetune_train.jsonl"
DEFAULT_OUTPUT = ROOT / ".models" / "alertissimo-qlora"
DEFAULT_MODEL = "Qwen/Qwen3-8B"


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            messages = row["messages"]
            if (
                not isinstance(messages, list)
                or len(messages) < 2
                or messages[0]["role"] != "user"
                or messages[1]["role"] != "assistant"
            ):
                raise ValueError("expected user and assistant messages")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid dataset row {line_number}: {exc}") from exc
        rows.append(row)
    if not rows:
        raise ValueError(f"dataset is empty: {path}")
    return rows


def _split_rows(rows: list[dict[str, Any]], eval_ratio: float, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        answer = str(row["messages"][1]["content"])
        groups.setdefault(answer, []).append(row)
    answers = list(groups)
    random.Random(seed).shuffle(answers)
    eval_count = max(1, round(len(answers) * eval_ratio))
    if eval_count >= len(answers):
        raise ValueError("eval split leaves no training groups; lower --eval-ratio")
    eval_answers = set(answers[:eval_count])
    train = [row for answer, group in groups.items() if answer not in eval_answers for row in group]
    evaluation = [row for answer, group in groups.items() if answer in eval_answers for row in group]
    return train, evaluation


def _format_row(row: dict[str, Any], tokenizer: Any) -> dict[str, str]:
    # Qwen3 can emit a hidden reasoning block.  The target here is a short,
    # canonical DSL program, so disable thinking in the chat template.
    return {
        "text": tokenizer.apply_chat_template(
            row["messages"],
            tokenize=False,
            add_generation_prompt=False,
            enable_thinking=False,
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--eval-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--gradient-accumulation", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--logging-steps", type=int, default=5)
    parser.add_argument(
        "--save-steps",
        type=int,
        default=50,
        help="Save a resumable checkpoint every N optimizer steps.",
    )
    parser.add_argument("--resume-from-checkpoint", type=Path)
    args = parser.parse_args()

    if not 0 < args.eval_ratio < 1:
        parser.error("--eval-ratio must be between 0 and 1")
    if args.save_steps < 1:
        parser.error("--save-steps must be at least 1")

    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        raise SystemExit(
            "Missing QLoRA dependency. Install with: "
            "pip install -r requirements-qlora.txt"
        ) from exc

    if not torch.cuda.is_available():
        raise SystemExit("QLoRA requires a CUDA GPU; torch.cuda.is_available() is false.")

    rows = _load_rows(args.dataset)
    train_rows, eval_rows = _split_rows(rows, args.eval_ratio, args.seed)
    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    train_dataset = Dataset.from_list([_format_row(row, tokenizer) for row in train_rows])
    eval_dataset = Dataset.from_list([_format_row(row, tokenizer) for row in eval_rows])
    compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=quantization,
        device_map="auto",
        dtype=compute_dtype,
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model)

    lora = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    training_kwargs: dict[str, Any] = dict(
        output_dir=str(args.output),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=args.learning_rate,
        logging_steps=args.logging_steps,
        # Keep evaluation and saving on the same schedule so that
        # load_best_model_at_end remains valid. Step checkpoints make an
        # interrupted Colab session resumable before the epoch completes.
        eval_strategy="steps",
        eval_steps=args.save_steps,
        save_strategy="steps",
        save_steps=args.save_steps,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        bf16=compute_dtype == torch.bfloat16,
        fp16=compute_dtype == torch.float16,
        gradient_checkpointing=True,
        optim="paged_adamw_8bit",
        dataset_text_field="text",
        # The NLP requests are short and the DSL targets are short.  Packing
        # multiple examples into each sequence avoids wasting most of a batch
        # on padding and is substantially faster on a T4.
        packing=True,
        seed=args.seed,
        report_to="none",
    )
    # Current TRL uses max_length and processing_class.  The old
    # max_seq_length/tokenizer spellings are intentionally not used here.
    training_kwargs["max_length"] = args.max_seq_length
    training_kwargs["gradient_checkpointing_kwargs"] = {"use_reentrant": False}
    training_kwargs["save_total_limit"] = 2
    training = SFTConfig(**training_kwargs)
    trainer_kwargs: dict[str, Any] = dict(
        model=model,
        args=training,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        peft_config=lora,
    )
    trainer_kwargs["processing_class"] = tokenizer
    trainer = SFTTrainer(
        **trainer_kwargs,
    )
    trainer.train(resume_from_checkpoint=str(args.resume_from_checkpoint) if args.resume_from_checkpoint else None)
    trainer.save_model(str(args.output))
    tokenizer.save_pretrained(str(args.output))
    print(f"saved QLoRA adapter to {args.output}")
    print(f"train rows: {len(train_rows)}; eval rows: {len(eval_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
