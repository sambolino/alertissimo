# Local Qwen3 QLoRA model

This project uses Ollama for local inference. Ollama is a system dependency,
not a Python package, so it does not belong in `requirements.txt`.

## Requirements

- Ollama `>= 0.33.0`
- the base model `qwen3:8b`
- the trained adapter file `models/alertissimo-qlora.gguf`
- this repository, including `Modelfile.qlora`

Install Ollama on Linux, macOS, or Windows using the instructions at
<https://ollama.com/download>. On Linux, the usual command is:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Verify the installation and download the base model:

```bash
ollama --version
ollama pull qwen3:8b
```

## Create the fine-tuned model

From the repository root, confirm that the adapter exists:

```bash
ls -lh models/alertissimo-qlora.gguf
```

Then create the local Ollama model:

```bash
ollama create alertissimo-qwen3-qlora -f Modelfile.qlora
```

Run it interactively:

```bash
ollama run alertissimo-qwen3-qlora
```

The `Modelfile.qlora` connects the existing `qwen3:8b` base to the QLoRA
adapter and sets the DSL system prompt, deterministic temperature, and output
limit.

## Evaluate the model

Install the Python project dependencies, if needed:

```bash
python -m pip install -e .
```

Run the same 15-example development set used for the original Ollama baseline:

```bash
python examples/evaluate_local_nlp.py \
  --model alertissimo-qwen3-qlora \
  --output examples/nlp_qlora_results.md
```

The report measures exact DSL, syntactically/semantically valid DSL, and
runnable DSL. It does not execute broker requests.

## Share with colleagues

### Share files directly

Send colleagues these files:

```text
Modelfile.qlora
models/alertissimo-qlora.gguf
```

They install Ollama, run `ollama pull qwen3:8b`, place the GGUF file under
`models/`, and run the `ollama create` command above. The GGUF adapter is kept
out of Git by `.gitignore` because it is a generated model artifact.

### Share through Ollama registry

After signing in to an Ollama registry, publish the already-created model:

```bash
ollama signin
ollama push YOUR_NAMESPACE/alertissimo-qwen3-qlora
```

Colleagues can then install and run it with:

```bash
ollama pull YOUR_NAMESPACE/alertissimo-qwen3-qlora
ollama run YOUR_NAMESPACE/alertissimo-qwen3-qlora
```

Do not commit the Ollama model cache or the raw Qwen3 base weights to this
repository. Share the adapter GGUF or the registry model instead.
