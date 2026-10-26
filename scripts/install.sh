#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PIP_CACHE_DIR="$PWD/var/cache/pip"
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
mkdir -p var/cache/matplotlib var/charts
export MPLCONFIGDIR="$PWD/var/cache/matplotlib"
export XDG_CACHE_HOME="$PWD/var/cache"
.venv/bin/msnr migrate
.venv/bin/msnr doctor
