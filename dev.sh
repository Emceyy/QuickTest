#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PYTHON="${PYTHON:-/Users/emreceylanuysal/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"
exec "$PYTHON" app.py

