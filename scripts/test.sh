#!/usr/bin/env bash
set -euo pipefail

export CHORETRACKER_SECRET_KEY="${CHORETRACKER_SECRET_KEY:-test}"
export CHORETRACKER_DISABLE_CSRF="${CHORETRACKER_DISABLE_CSRF:-1}"

uv run --with pytest --with httpx -m pytest "$@"
