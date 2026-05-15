#!/usr/bin/env bash
# verify-metrics.sh — boot the gateway in HTTP mode, scrape /metrics, and
# assert that the Four Golden Signals surface (CT-B-008) is present.
#
# This is an offline contract check: the gateway runs against whatever index
# state exists in db/ and tolerates missing Ollama (circuit breaker open is
# a valid metrics state). The script asserts METRIC NAMES, not values.
#
# Usage:
#   bash scripts/verify-metrics.sh           # boots gateway, scrapes, exits
#   PORT=8765 bash scripts/verify-metrics.sh # override port
#
# Exit codes:
#   0  all expected metric names present
#   1  invocation error / gateway failed to start
#   2  one or more expected metric names missing

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8765}"
PIDFILE="$(mktemp)"
LOGFILE="$(mktemp)"

cleanup() {
  if [ -s "$PIDFILE" ]; then
    pid="$(cat "$PIDFILE")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$PIDFILE" "$LOGFILE"
}
trap cleanup EXIT

cd "$REPO_ROOT"

echo "Booting gateway on PORT=$PORT in background..."
PORT="$PORT" python gateway.py > "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"

# Wait up to 30s for the /health endpoint to respond.
ready=0
for _ in $(seq 1 30); do
  if curl -sf "http://localhost:${PORT}/health" > /dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done

if [ "$ready" -ne 1 ]; then
  echo "ERROR: gateway did not become ready on http://localhost:${PORT}/health within 30s" >&2
  echo "--- gateway stdout/stderr ---" >&2
  cat "$LOGFILE" >&2
  exit 1
fi

metrics="$(curl -sf "http://localhost:${PORT}/metrics" || true)"
if [ -z "$metrics" ]; then
  echo "ERROR: /metrics returned no body" >&2
  exit 1
fi

# Four Golden Signals (Google SRE Book ch.6):
#   - Latency: tool_compass_embed_latency_p95_ms
#   - Traffic: tool_compass_search_total
#   - Errors:  tool_compass_backend_call_total{status="error"} (label form)
#              tool_compass_embed_failures_total
#   - Saturation: tool_compass_inflight_requests (CT-B-008 / BE-B-002)
#
# Plus operational gauges:
#   - tool_compass_ollama_available
#   - tool_compass_backend_up
#   - tool_compass_index_age_seconds
#   - tool_compass_orphaned_vectors

required_metrics=(
  "tool_compass_search_total"
  "tool_compass_ollama_available"
  "tool_compass_backend_up"
  "tool_compass_backend_call_total"
  "tool_compass_embed_latency_p95_ms"
  "tool_compass_embed_failures_total"
  "tool_compass_index_age_seconds"
  "tool_compass_orphaned_vectors"
)

# CT-B-008 saturation gauges. These are warn-only until BE-B-002 lands the
# backend-domain wiring. Once the gateway surface emits them, flip to fatal
# by moving them into required_metrics above.
saturation_metrics=(
  "tool_compass_inflight_requests"
  "tool_compass_inflight_backend_calls"
)

missing=0
for name in "${required_metrics[@]}"; do
  if ! grep -Fq "$name" <<<"$metrics"; then
    echo "FAIL: required metric '$name' not present in /metrics output" >&2
    missing=$((missing + 1))
  fi
done

saturation_missing=0
for name in "${saturation_metrics[@]}"; do
  if ! grep -Fq "$name" <<<"$metrics"; then
    saturation_missing=$((saturation_missing + 1))
  fi
done

if [ "$saturation_missing" -gt 0 ]; then
  echo "::warning::CT-B-008 saturation gauges still missing from /metrics — $saturation_missing of ${#saturation_metrics[@]} expected. Tracked under BE-B-002 (backend domain)."
fi

if [ "$missing" -gt 0 ]; then
  echo "ERROR: $missing required metric name(s) missing from /metrics" >&2
  exit 2
fi

echo "OK: all $(( ${#required_metrics[@]} )) required metric names present on /metrics."
echo "(CT-B-008 saturation gauges: $(( ${#saturation_metrics[@]} - saturation_missing )) of ${#saturation_metrics[@]} present.)"
exit 0
