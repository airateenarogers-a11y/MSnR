#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export MPLCONFIGDIR="$PWD/var/cache/matplotlib"
export XDG_CACHE_HOME="$PWD/var/cache"
exec .venv/bin/msnr serve --host 127.0.0.1 --port "${MSNR_PORT:-8000}"
