#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

is_pid_running() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1
}

ensure_not_running() {
  if [[ -f "${PID_FILE}" ]]; then
    local existing_pid
    existing_pid="$(<"${PID_FILE}")"
    if is_pid_running "${existing_pid}"; then
      echo "Inference server already running with PID ${existing_pid}."
      echo "Run 'make stop' before starting another server."
      return 1
    fi
    rm -f "${PID_FILE}"
  fi
}

vllm_quant_args() {
  case "${MODEL_QUANT}" in
    awq|fp8|gptq)
      printf -- "--quantization %s" "${MODEL_QUANT}"
      ;;
    *)
      printf ""
      ;;
  esac
}

main() {
  load_env_files

  local requested_model="${MODEL:-${MODEL_NAME:-llama3-8b}}"
  resolve_model "${requested_model}"

  local port="${PORT:-${DEFAULT_PORT:-11434}}"
  local log_file="/tmp/llm_server_${MODEL_ALIAS}.log"

  ensure_not_running

  case "${MODEL_BACKEND}" in
    ollama)
      if ! command_exists ollama; then
        echo "Ollama is not installed. Run 'make setup MODEL=${MODEL_ALIAS}' first." >&2
        return 1
      fi
      echo "Starting Ollama on http://localhost:${port}/v1"
      OLLAMA_HOST="0.0.0.0:${port}" ollama serve >"${log_file}" 2>&1 &
      ;;
    vllm)
      if ! python3 - <<'PY' >/dev/null 2>&1
import vllm
PY
      then
        echo "vLLM is not installed. Run 'make setup MODEL=${MODEL_ALIAS}' first." >&2
        return 1
      fi

      local tensor_parallel_size="${GPU_COUNT:-1}"
      if [[ "${tensor_parallel_size}" == "0" ]]; then
        tensor_parallel_size=1
      fi

      local quant_args
      quant_args="$(vllm_quant_args)"
      echo "Starting vLLM on http://localhost:${port}/v1"
      # shellcheck disable=SC2086
      python3 -m vllm.entrypoints.openai.api_server \
        --host 0.0.0.0 \
        --port "${port}" \
        --model "${MODEL_REF}" \
        --served-model-name "${MODEL_ALIAS}" \
        --tensor-parallel-size "${tensor_parallel_size}" \
        ${quant_args} >"${log_file}" 2>&1 &
      ;;
    *)
      echo "Unsupported backend '${MODEL_BACKEND}' for model '${MODEL_ALIAS}'." >&2
      return 1
      ;;
  esac

  local pid=$!
  echo "${pid}" >"${PID_FILE}"
  echo "Server PID ${pid} written to ${PID_FILE}"
  echo "Logs: ${log_file}"
}

main "$@"
