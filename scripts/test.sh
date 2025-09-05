#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python}"
"$PYTHON" "$(dirname "$0")/test.py" "$@"
