# QLoRA training

The checked-in dataset is `dataset/nlp_finetune_train.jsonl`. It contains 720
validated English-to-Alertissimo-DSL examples in chat format.

Install the optional GPU dependencies in an environment with a CUDA-enabled
PyTorch build:

```bash
pip install -r requirements-qlora.txt
```

Run a first training job:

```bash
python scripts/train_qlora.py \
  --model Qwen/Qwen3-8B \
  --output .models/alertissimo-qlora
```

`qwen3:8b` is the Ollama tag used for inference. QLoRA itself uses the
corresponding Hugging Face checkpoint `Qwen/Qwen3-8B` (or a local directory
containing that checkpoint), because Transformers/bitsandbytes must access the
model weights directly. The Ollama tag is not passed to `AutoModelForCausalLM`.

The script uses 4-bit NF4 quantization, double quantization, paged 8-bit AdamW,
gradient checkpointing, and LoRA adapters. It writes the adapter and tokenizer
to the output directory; the full base model is not copied there.

To evaluate the adapter on the same 15 examples as the Ollama baseline:

```bash
python examples/evaluate_qlora.py \
  --adapter models/alertissimo-qlora \
  --base-model Qwen/Qwen3-8B
```

The evaluation report is written to `examples/nlp_qlora_results.md`.

For local Ollama deployment, convert the saved adapter with llama.cpp:

```bash
python /path/to/llama.cpp/convert_lora_to_gguf.py \
  models/alertissimo-qlora \
  --base-model-id Qwen/Qwen3-8B \
  --outfile models/alertissimo-qlora.gguf \
  --outtype f16
ollama create alertissimo-qwen3-qlora -f Modelfile.qlora
```

The evaluation split is made by canonical DSL answer rather than by individual
row, preventing paraphrases of the same DSL program from appearing in both
splits. The default split is 85/15 and is deterministic with `--seed`.

For a smaller smoke run, use `--epochs 0.1 --logging-steps 1`. QLoRA requires a
CUDA GPU; use `--help` to adjust batch size, sequence length, and checkpoint
resumption for the available card.
