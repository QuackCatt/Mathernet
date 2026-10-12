#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-python3}
VENV="$ROOT/.venv"

cd "$ROOT"

if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON" -m venv "$VENV"
fi

if [ ! -f "$ROOT/.env" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
fi

"$ROOT/scripts/mathernet" init
printf '%s\n' "Setup complete. Next: edit .env, then run scripts/mathernet demo"
