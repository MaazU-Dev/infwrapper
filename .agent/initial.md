# Local LLM Infrastructure — Project Documentation

---

## Mission Statement

This project exists to give any developer **full, reproducible, hardware-aware control** over running open-source large language models — locally on a personal machine or remotely on a cloud GPU (H100) — without vendor lock-in, recurring API costs, or opaque infrastructure.

The core belief is that inference should be a **first-class engineering artifact**: version-controlled, scriptable, portable, and observable. A model should be provisionable with a single command, swappable via a config file, and tearable down cleanly — the same way any other piece of infrastructure is managed.

### Goals

- **Reproducibility** — Any team member on any supported machine should be able to run `make setup-run MODEL=<alias>` and reach a working inference endpoint within minutes, with no tribal knowledge required.
- **Hardware portability** — The same codebase targets a consumer GPU (local PC) and a data-center GPU (H100) without branching logic in application code. The backend engine (Ollama vs. vLLM) is resolved automatically based on detected hardware.
- **OpenAI API compatibility** — Every model, regardless of origin or backend, is served behind an OpenAI-compatible REST interface. Application code, Claude Code, and external tooling require zero modification when switching models or machines.
- **Separation of concerns** — Environment setup, model provisioning, inference serving, and teardown are independent, composable operations. Each can be run in isolation or chained together.
- **Responsible model selection** — Models are chosen based on hardware fit, benchmark alignment to the task domain, and license terms. Quantization format is selected from battle-tested community builds rather than produced ad hoc.

### Non-Goals

- This project does not fine-tune or train models.
- It does not manage multi-tenant inference or autoscaling (that is a production serving concern beyond this scope).
- It does not abstract over closed-source APIs (OpenAI, Anthropic, etc.) — it is exclusively for self-hosted open-weight models.

---

## Project Structure

```
llm-local/
├── Makefile                    # Top-level orchestrator — all operations go through here
├── .env.example                # Template for required environment variables
├── .env                        # Local overrides (git-ignored)
│
├── config/
│   └── models.conf             # Curated model registry: alias, repo, backend, quantization
│
├── scripts/
│   ├── setup_env.sh            # Detects hardware, installs Ollama or vLLM accordingly
│   ├── setup_model.sh          # Pulls or caches the target model from HuggingFace / Ollama
│   ├── run_model.sh            # Starts the inference server on the specified port
│   ├── setup_and_run.sh        # Convenience wrapper: setup_env + setup_model + run_model
│   └── cleanup.sh              # Stops the server process and optionally frees VRAM
│
└── api/
    └── proxy.py                # Optional FastAPI reverse proxy (adds auth, logging, routing)
```

### File Responsibilities

#### `Makefile`
The single entry point for all operations. Accepts `MODEL` and `PORT` as arguments, delegates to the appropriate script. Provides a `help` target that documents all available commands. This is the file a new developer reads first.

#### `.env` / `.env.example`
Stores `MODEL_NAME`, `PORT`, `LLM_BACKEND_URL`, and any HuggingFace tokens required for gated models (e.g., Llama 3). The `.env` file is git-ignored; `.env.example` is committed as a reference template.

#### `config/models.conf`
The central model registry. Each line maps a short human alias to a fully qualified HuggingFace repo or Ollama model name, a backend engine, and a quantization format. This is the **only file that changes** when adding or removing a model. Format:

```
# ALIAS|HF_REPO_OR_OLLAMA_NAME|BACKEND|QUANT
llama3-8b|meta-llama/Meta-Llama-3.1-8B-Instruct|ollama|Q4_K_M
qwen-14b|Qwen/Qwen2.5-14B-Instruct|ollama|Q5_K_M
llama3-70b|meta-llama/Llama-3.3-70B-Instruct|vllm|fp8
deepseek-r1|deepseek-ai/DeepSeek-R1-Distill-Llama-70B|vllm|awq
```

#### `scripts/setup_env.sh`
Runs hardware detection via `nvidia-smi`. On a consumer GPU it installs Ollama; on an H100 (>70GB VRAM) it installs vLLM. Writes a `.env.detected` file that downstream scripts source. Idempotent — safe to run multiple times.

#### `scripts/setup_model.sh`
Reads `models.conf` for the given alias and either runs `ollama pull` (for Ollama backends) or uses `huggingface_hub.snapshot_download` to pre-cache the model weights (for vLLM backends). Validates the alias exists in config before proceeding.

#### `scripts/run_model.sh`
Starts the inference server in the background. For Ollama, sets `OLLAMA_HOST` and starts `ollama serve`. For vLLM, launches `vllm.entrypoints.openai.api_server` with automatic tensor parallelism scaled to the number of available GPUs. Writes the server PID to `/tmp/llm_server.pid` for use by `cleanup.sh`.

#### `scripts/cleanup.sh`
Accepts `stop` (kill server process) or `full` (kill process + flush VRAM via PyTorch). Reads the PID file and also sends `pkill` signals to known process names as a fallback.

#### `api/proxy.py`
An optional FastAPI application that sits in front of the inference backend. Useful for adding API key authentication, request logging, rate limiting, or routing traffic between local and cloud backends. Exposes the same `/v1/chat/completions` interface as the underlying engine, so clients require no reconfiguration.

---

## Hardware & Backend Matrix

| Hardware | VRAM | Backend | Quantization |
|---|---|---|---|
| Consumer GPU (RTX 3060–4090) | 8–24 GB | Ollama + llama.cpp | Q4_K_M / Q5_K_M |
| Workstation GPU (RTX 3090 Ti, A6000) | 24–48 GB | Ollama or vLLM | Q5_K_M / Q8_0 |
| Cloud H100 | 80 GB | vLLM | FP8 / BF16 / AWQ |
| CPU-only | RAM-limited | Ollama + llama.cpp | Q4_K_M (small models only) |

---

## End-to-End Workflow

### First-Time Setup (New Machine)

```bash
# 1. Clone the repo
git clone https://github.com/your-org/llm-local && cd llm-local

# 2. Copy environment template and fill in any HuggingFace tokens
cp .env.example .env

# 3. Full setup and launch in one command
make setup-run MODEL=llama3-8b
# → Detects hardware
# → Installs Ollama or vLLM
# → Pulls/caches model weights
# → Starts inference server on port 11434
# → OpenAI-compatible endpoint live at http://localhost:11434/v1
```

### Day-to-Day Usage

```bash
# Start a specific model (already downloaded)
make run MODEL=llama3-8b

# Start on a custom port
make run MODEL=qwen-14b PORT=8080

# See all configured model aliases
make list-models

# Stop the running server
make stop

# Stop server and flush GPU memory
make clean
```

### Switching to H100 (Cloud)

```bash
# SSH into your H100 instance, clone repo, then:
make setup-run MODEL=llama3-70b PORT=8000

# On your local machine, point your client at the remote:
export LLM_BACKEND_URL="http://<h100-ip>:8000/v1"
```

### Adding a New Model

```bash
# 1. Add one line to config/models.conf
echo "phi4-mini|microsoft/Phi-4-mini-instruct|ollama|Q4_K_M" >> config/models.conf

# 2. Pull and run — no other files need to change
make setup-run MODEL=phi4-mini
```

### Pointing Claude Code at Your Local or H100 Model

**Per-machine (global):**
```bash
# ~/.claude/settings.json
{
  "model": "llama3-8b",
  "apiBaseUrl": "http://localhost:11434/v1",
  "apiKey": "none"
}
```

**Per-project (committed to repo, targets H100):**
```bash
# .claude/settings.json  (in project root)
{
  "model": "llama3-70b",
  "apiBaseUrl": "http://<h100-ip>:8000/v1",
  "apiKey": "your-optional-proxy-key"
}
```

Switching between local and cloud is a matter of which directory you run Claude Code from — the project-level settings file takes precedence over the global one.

### Consuming the API from Application Code

```python
from openai import OpenAI

# Works identically whether backend is Ollama (local) or vLLM (H100)
client = OpenAI(
    base_url="http://localhost:11434/v1",  # or H100 URL
    api_key="none"
)

response = client.chat.completions.create(
    model="llama3-8b",          # matches the alias in models.conf
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Explain quantization in one paragraph."}
    ],
    stream=True
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

---

## Key Design Decisions

**Why pre-quantized models over self-quantization?**
Community-produced GGUF and AWQ builds (bartowski, TheBloke, model authors) are calibrated on diverse datasets, widely tested, and available within hours of a model release. Self-quantization is reserved for cases where no community build exists yet or a custom calibration dataset is required.

**Why OpenAI-compatible APIs?**
It decouples the inference backend from every consumer of the model. Application code, Claude Code, LangChain, and any other tooling that supports the OpenAI SDK will work without modification. The proxy layer in `api/proxy.py` further insulates application code from backend changes.

**Why Makefile as the orchestrator?**
Make is universally available, has no runtime dependencies, handles argument passing cleanly, and its `help` target serves as self-documenting runbook. It delegates actual logic to bash scripts, so each operation remains testable in isolation.

**Why separate scripts for env, model, and run?**
CI pipelines, Docker entrypoints, and deployment scripts often need to call only one of these phases. Keeping them separate makes the project composable with external tooling without modification.