#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"${SCRIPT_DIR}/setup_env.sh"
"${SCRIPT_DIR}/setup_model.sh"
"${SCRIPT_DIR}/run_model.sh"
