#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

install_ollama() {
  if command_exists ollama; then
    echo "Ollama is already installed."
    return
  fi

  case "$(uname -s)" in
    Darwin)
      if command_exists brew; then
        brew install ollama
      else
        echo "Homebrew is required to install Ollama automatically on macOS." >&2
        echo "Install Ollama manually from https://ollama.com/download, then rerun this command." >&2
        return 1
      fi
      ;;
    Linux)
      if command_exists curl; then
        curl -fsSL https://ollama.com/install.sh | sh
      else
        echo "curl is required to install Ollama automatically on Linux." >&2
        return 1
      fi
      ;;
    *)
      echo "Unsupported OS for automatic Ollama installation: $(uname -s)" >&2
      return 1
      ;;
  esac
}

install_vllm() {
  if python3 - <<'PY' >/dev/null 2>&1
import vllm
PY
  then
    echo "vLLM is already installed."
    return
  fi

  if ! command_exists python3; then
    echo "python3 is required to install vLLM." >&2
    return 1
  fi

  python3 -m pip install --upgrade pip
  python3 -m pip install --upgrade vllm huggingface_hub
}

detect_hardware() {
  if command_exists nvidia-smi; then
    local gpu_count max_vram_mb
    gpu_count="$(nvidia-smi --query-gpu=name --format=csv,noheader | wc -l | tr -d ' ')"
    max_vram_mb="$(
      nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits |
        awk 'BEGIN { max = 0 } { if ($1 > max) max = $1 } END { print max + 0 }'
    )"

    if (( max_vram_mb >= 70000 )); then
      echo "vllm|h100|${gpu_count}|${max_vram_mb}|8000"
    else
      echo "ollama|nvidia-consumer|${gpu_count}|${max_vram_mb}|11434"
    fi
    return
  fi

  echo "ollama|cpu-only|0|0|11434"
}

main() {
  local detected backend profile gpu_count max_vram_mb default_port
  detected="$(detect_hardware)"
  IFS='|' read -r backend profile gpu_count max_vram_mb default_port <<<"${detected}"

  echo "Detected hardware profile: ${profile} (${gpu_count} GPU(s), max VRAM ${max_vram_mb} MB)"
  echo "Selected backend: ${backend}"

  case "${backend}" in
    ollama) install_ollama ;;
    vllm) install_vllm ;;
    *)
      echo "Unsupported backend detected: ${backend}" >&2
      return 1
      ;;
  esac

  write_detected_env "${backend}" "${profile}" "${gpu_count}" "${max_vram_mb}" "${default_port}"
  echo "Wrote ${DETECTED_ENV_FILE}"
}

main "$@"
