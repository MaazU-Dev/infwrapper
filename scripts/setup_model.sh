#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

main() {
  load_env_files

  local requested_model="${MODEL:-${MODEL_NAME:-llama3-8b}}"
  resolve_model "${requested_model}"

  echo "Provisioning model '${MODEL_ALIAS}'"
  echo "  ref:     ${MODEL_REF}"
  echo "  backend: ${MODEL_BACKEND}"
  echo "  quant:   ${MODEL_QUANT}"

  case "${MODEL_BACKEND}" in
    ollama)
      if ! command_exists ollama; then
        echo "Ollama is not installed. Run 'make setup MODEL=${MODEL_ALIAS}' first." >&2
        return 1
      fi
      ollama pull "${MODEL_REF}"
      # Create a stable local alias so OpenAI-compatible clients can use MODEL_ALIAS.
      if [[ "${MODEL_REF}" != "${MODEL_ALIAS}" ]]; then
        ollama cp "${MODEL_REF}" "${MODEL_ALIAS}" >/dev/null
      fi
      ;;
    vllm)
      if ! command_exists python3; then
        echo "python3 is required to cache HuggingFace models for vLLM." >&2
        return 1
      fi
      HF_MODEL_REF="${MODEL_REF}" python3 - <<'PY'
import os
from huggingface_hub import snapshot_download

repo_id = os.environ["HF_MODEL_REF"]
token = os.environ.get("HF_TOKEN") or None
path = snapshot_download(repo_id=repo_id, token=token)
print(f"Cached {repo_id} at {path}")
PY
      ;;
    *)
      echo "Unsupported backend '${MODEL_BACKEND}' for model '${MODEL_ALIAS}'." >&2
      return 1
      ;;
  esac
}

main "$@"
