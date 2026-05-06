# infwrapper

`infwrapper` is a local LLM infrastructure wrapper that standardizes model setup and serving behind an OpenAI-compatible API, with an optional FastAPI proxy layer.

## Purpose

This repository helps you:

- detect local hardware and choose a serving backend automatically (`ollama` or `vLLM`)
- provision model weights from aliases defined in `config/models.conf`
- run a local OpenAI-compatible inference endpoint
- expose an optional proxy (`api/proxy.py`) that can forward `/v1/*` requests, enforce an API key, and translate Claude-style payloads to OpenAI format

In short: it provides a repeatable way to boot and use local models with consistent API behavior.

## Setup

### 1) Prerequisites

- macOS or Linux
- `python3`
- `make`
- `brew` (optional, used for auto-installing Ollama on macOS)

> The setup scripts install backend dependencies automatically where possible.

### 2) Configure environment

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` as needed:

- `MODEL_NAME` default alias from `config/models.conf` (for example `llama3-8b`)
- `PORT` inference server port (default `11434`)
- `LLM_BACKEND_URL` backend URL used by the proxy (default `http://localhost:11434/v1`)
- `HF_TOKEN` optional token for gated Hugging Face models (vLLM only)
- `PROXY_API_KEY` optional bearer key for the proxy
- `PROXY_PORT` proxy port (default `8081`)

### 3) One-command setup + run

Set up backend tooling, pull model weights, and start inference:

```bash
make setup-run MODEL=llama3-8b PORT=11434
```

### 4) Start proxy (optional)

Run the FastAPI proxy:

```bash
make run-proxy PROXY_PORT=8081
```

The proxy health endpoint:

```bash
curl http://localhost:8081/health
```

## Common commands

```bash
make list-models                # list configured model aliases
make setup MODEL=llama3-8b      # detect hardware and install backend dependencies
make setup-model MODEL=llama3-8b
make run-model MODEL=llama3-8b PORT=11434
make run-proxy PROXY_PORT=8081
make stop                       # stop inference server
make clean                      # stop server + cleanup
```

## Quick API checks

Call backend directly:

```bash
curl http://localhost:11434/v1/models
```

Call through proxy:

```bash
curl http://localhost:8081/v1/models
```

If you set `PROXY_API_KEY`, include:

```bash
-H "Authorization: Bearer <your-key>"
```
