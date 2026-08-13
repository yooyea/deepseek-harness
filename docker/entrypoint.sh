#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DSH_ACCESS_PASSWORD:-}" ]]; then
  echo "DSH_ACCESS_PASSWORD must be set before starting the container." >&2
  exit 1
fi

export DSH_ACCESS_USER="${DSH_ACCESS_USER:-admin}"
export DSH_ACCESS_HASH
DSH_ACCESS_HASH="$(caddy hash-password --plaintext "$DSH_ACCESS_PASSWORD")"

mkdir -p "$DSH_HOME"

node /opt/dsh/apps/cli/lib/bin.js web --host 127.0.0.1 --port 3080 &
dsh_pid=$!

caddy run --config /opt/dsh/docker/Caddyfile --adapter caddyfile &
caddy_pid=$!

shutdown() {
  kill -TERM "$dsh_pid" "$caddy_pid" 2>/dev/null || true
  wait "$dsh_pid" "$caddy_pid" 2>/dev/null || true
}

trap shutdown INT TERM EXIT

wait -n "$dsh_pid" "$caddy_pid"
