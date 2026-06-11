#!/usr/bin/env sh
# Translate environment configuration into `chassis serve` flags.
#
# Recognised env vars:
#   CHASSIS_HOST  bind host           (default 0.0.0.0)
#   CHASSIS_PORT  bind port           (default 8000)
#   CHASSIS_DB    registry store DSN  (default in-memory if unset)
#
# Any extra arguments are passed straight through, so this image can also run
# one-off chassis commands, e.g. `docker run --rm IMAGE gate /manifests/*.json`.
set -eu

if [ "$#" -gt 0 ]; then
    exec chassis "$@"
fi

HOST="${CHASSIS_HOST:-0.0.0.0}"
PORT="${CHASSIS_PORT:-8000}"

set -- serve --host "$HOST" --port "$PORT"
if [ -n "${CHASSIS_DB:-}" ]; then
    set -- "$@" --db "$CHASSIS_DB"
fi

exec chassis "$@"
