SHELL := /usr/bin/env bash

MODEL ?= llama3-8b
PORT ?= 11434
PROXY_PORT ?= 8081

.PHONY: help setup setup-model run setup-run list-models stop clean proxy

help:
	@printf "Local LLM infrastructure\n\n"
	@printf "Usage:\n"
	@printf "  make setup MODEL=<alias> [PORT=<port>]      Detect hardware and install backend\n"
	@printf "  make setup-model MODEL=<alias>             Pull/cache model weights\n"
	@printf "  make run MODEL=<alias> [PORT=<port>]       Start OpenAI-compatible server\n"
	@printf "  make setup-run MODEL=<alias> [PORT=<port>] Setup, provision, and run\n"
	@printf "  make list-models                           Show configured model aliases\n"
	@printf "  make stop                                  Stop running inference server\n"
	@printf "  make clean                                 Stop server and attempt VRAM cleanup\n"
	@printf "  make proxy [PROXY_PORT=<port>]             Start optional FastAPI proxy\n\n"
	@printf "Defaults: MODEL=%s PORT=%s\n" "$(MODEL)" "$(PORT)"

setup:
	@MODEL="$(MODEL)" PORT="$(PORT)" scripts/setup_env.sh

setup-model:
	@MODEL="$(MODEL)" scripts/setup_model.sh

run:
	@MODEL="$(MODEL)" PORT="$(PORT)" scripts/run_model.sh

setup-run:
	@MODEL="$(MODEL)" PORT="$(PORT)" scripts/setup_and_run.sh

list-models:
	@awk -F'|' 'NF == 4 && $$1 !~ /^#/ { printf "%-14s %-8s %-8s %s\n", $$1, $$3, $$4, $$2 }' config/models.conf

stop:
	@scripts/cleanup.sh stop

clean:
	@scripts/cleanup.sh full

proxy:
	@set -a; [[ ! -f .env ]] || source .env; set +a; uvicorn api.proxy:app --host 0.0.0.0 --port "$${PROXY_PORT:-$(PROXY_PORT)}"
