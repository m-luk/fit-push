#!/usr/bin/env sh
# Start fit-git: creates .venv and installs requirements on first run (or when they change).
#   ./scripts/run.sh                       # http://127.0.0.1:8000
#   PORT=9000 RELOAD=1 ./scripts/run.sh
set -e
cd "$(dirname "$0")/.."

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

if [ ! -x .venv/bin/python ]; then
    echo "Creating virtual environment in .venv ..."
    python3 -m venv .venv
fi
PY=.venv/bin/python

REQ=requirements.txt
[ -n "$DEV" ] && REQ=requirements-dev.txt
HASH="$(cat requirements.txt $( [ -n "$DEV" ] && echo requirements-dev.txt ) | cksum)"
if [ ! -f .venv/.fitgit-requirements ] || [ "$(cat .venv/.fitgit-requirements)" != "$HASH" ]; then
    echo "Installing $REQ ..."
    "$PY" -m pip install --disable-pip-version-check -q -r "$REQ"
    echo "$HASH" > .venv/.fitgit-requirements
fi

set -- --host "$HOST" --port "$PORT"
[ -n "$RELOAD" ] && set -- "$@" --reload
echo "fit-git on http://$HOST:$PORT  (Ctrl+C to stop)"
exec "$PY" -m app "$@"
