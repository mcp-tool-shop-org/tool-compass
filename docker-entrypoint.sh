#!/bin/sh
# Say out loud whether the semantic index will survive this container.
#
# Tool Compass's value is the index: embedding every tool in every configured
# MCP server takes real time and real compute, and the result lives in
# /app/tool_compass/db. Without a volume that directory is ordinary container
# filesystem, so the index is discarded when the container exits and rebuilt
# from scratch on the next start -- which looks like "Tool Compass is slow",
# not like "you forgot a -v".
#
# docker-compose.yml already mounts the `compass-data` named volume, so compose
# users are fine. This exists for the bare `docker run ghcr.io/...` path, which
# is what someone trying the published image reaches for first and which has no
# volume at all.
#
# A warning rather than a refusal: `--version`, `--help` and a one-off query
# are all legitimate without persistence, and a container that refuses to start
# is a worse first experience than one that tells you what it is about to do.
#
# stderr, deliberately. This is a warning about the environment, not output of
# the command being run -- on stdout it corrupts anything piping the container,
# which is how the sibling xrpl-camp image broke its own release check.

set -eu

DATA_DIR="${TOOL_COMPASS_DB_DIR:-/app/tool_compass/db}"

is_mounted() {
    # A bind mount or named volume puts DATA_DIR on a different device from /.
    # Compare the two rather than reading a mount table, which is not reliably
    # readable inside the container.
    root_dev=$(stat -c %d / 2>/dev/null || echo 0)
    data_dev=$(stat -c %d "$DATA_DIR" 2>/dev/null || echo 0)
    [ "$root_dev" != "$data_dev" ]
}

if [ -d "$DATA_DIR" ] && ! is_mounted; then
    printf '\033[33m' >&2
    cat >&2 <<WARNING
  ${DATA_DIR} is not mounted.

  Tool Compass keeps its semantic index there. Without a volume the index is
  discarded when this container exits, and every start pays the full embedding
  cost again -- which reads as "it is slow" rather than as a missing flag.

  Keep it between runs:

      docker run --rm -p 7860:7860 -v tool-compass-data:${DATA_DIR} \\
        ghcr.io/mcp-tool-shop-org/tool-compass:latest

  Or use the compose file, which already mounts a named volume:

      docker compose up

WARNING
    printf '\033[0m' >&2
fi

exec "$@"
