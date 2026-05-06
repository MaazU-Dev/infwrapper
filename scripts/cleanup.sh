#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

stop_server() {
  if [[ -f "${PID_FILE}" ]]; then
    local pid
    pid="$(<"${PID_FILE}")"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
      echo "Stopping inference server PID ${pid}"
      kill "${pid}" || true
      sleep 2
      if kill -0 "${pid}" >/dev/null 2>&1; then
        echo "PID ${pid} did not exit cleanly; sending SIGKILL"
        kill -9 "${pid}" || true
      fi
    else
      echo "PID file exists, but process is not running."
    fi
    rm -f "${PID_FILE}"
  else
    echo "No PID file found at ${PID_FILE}."
  fi

  pkill -f "vllm.entrypoints.openai.api_server" >/dev/null 2>&1 || true
}

flush_vram() {
  if command_exists nvidia-smi; then
    echo "Current GPU memory usage:"
    nvidia-smi || true
  fi

  if command_exists python3; then
    python3 - <<'PY' || true
try:
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
        print("Requested PyTorch CUDA cache cleanup.")
except Exception as exc:
    print(f"Skipping PyTorch CUDA cleanup: {exc}")
PY
  fi
}

main() {
  local mode="${1:-stop}"
  case "${mode}" in
    stop)
      stop_server
      ;;
    full)
      stop_server
      flush_vram
      ;;
    *)
      echo "Usage: $0 {stop|full}" >&2
      return 1
      ;;
  esac
}

main "$@"
