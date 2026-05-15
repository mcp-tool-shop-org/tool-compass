#!/usr/bin/env bash
# regenerate-scorecard.sh — refresh SCORECARD.md from shipcheck without
# clobbering hand-curated sections (CT-B-017).
#
# The shipcheck auto-generated block lives between two markers:
#
#   <!-- SHIPCHECK-AUTO-START -->
#   ... (totals table, hard-gate breakdown) ...
#   <!-- SHIPCHECK-AUTO-END -->
#
# Sections OUTSIDE those markers (Known Gaps, Remediation History,
# operator notes) are preserved verbatim across regenerations.
#
# Usage:
#   bash scripts/regenerate-scorecard.sh           # refresh SCORECARD.md in place
#   bash scripts/regenerate-scorecard.sh --check   # verify SCORECARD.md is fresh (CI gate)
#
# Exit codes:
#   0  success / scorecard fresh
#   1  invocation error
#   2  --check failed (drift detected)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCORECARD="${REPO_ROOT}/SCORECARD.md"

# Marker pair — must match exactly what's written to SCORECARD.md by this script.
START_MARKER="<!-- SHIPCHECK-AUTO-START -->"
END_MARKER="<!-- SHIPCHECK-AUTO-END -->"

mode="apply"
if [ $# -gt 0 ]; then
  case "$1" in
    --check) mode="check" ;;
    --help|-h)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 1
      ;;
  esac
fi

if [ ! -f "$SCORECARD" ]; then
  echo "ERROR: $SCORECARD not found" >&2
  exit 1
fi

# Pull the freshest shipcheck output into a tempfile.
fresh="$(mktemp)"
trap 'rm -f "$fresh" "${fresh}.merged" 2>/dev/null || true' EXIT

if ! npx --yes @mcptoolshop/shipcheck audit --format markdown > "$fresh" 2>/dev/null; then
  echo "ERROR: 'npx @mcptoolshop/shipcheck audit' failed — is shipcheck installed and the repo audit-ready?" >&2
  exit 1
fi

# Build the merged file: everything before the start marker (verbatim),
# the marker, the fresh auto block, the closing marker, then everything
# after the end marker (verbatim).
merged="${fresh}.merged"

if ! grep -q "$START_MARKER" "$SCORECARD"; then
  # First-time bootstrap path: SCORECARD.md exists but has no markers yet.
  # Append the auto block at the end so existing hand-curated text is kept.
  {
    cat "$SCORECARD"
    printf '\n%s\n' "$START_MARKER"
    cat "$fresh"
    printf '%s\n' "$END_MARKER"
  } > "$merged"
else
  awk -v start="$START_MARKER" -v end="$END_MARKER" -v fresh="$fresh" '
    BEGIN { state = "before" }
    state == "before" {
      if ($0 == start) {
        print start
        while ((getline line < fresh) > 0) print line
        close(fresh)
        print end
        state = "inside"
        next
      }
      print
      next
    }
    state == "inside" {
      if ($0 == end) { state = "after" }
      next
    }
    state == "after" { print }
  ' "$SCORECARD" > "$merged"
fi

if [ "$mode" = "check" ]; then
  if ! diff -u "$SCORECARD" "$merged" >/dev/null; then
    echo "SCORECARD.md is out of date with shipcheck output." >&2
    echo "Run 'bash scripts/regenerate-scorecard.sh' to refresh." >&2
    diff -u "$SCORECARD" "$merged" || true
    exit 2
  fi
  echo "OK: SCORECARD.md is in sync with shipcheck."
  exit 0
fi

cp "$merged" "$SCORECARD"
echo "Refreshed $SCORECARD"
