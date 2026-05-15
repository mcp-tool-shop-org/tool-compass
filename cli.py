"""Tool Compass — CLI entry point.

MCC-FT-001: subcommand shell that subsumes the old `gateway:main` entry so
`tool-compass` can be both a server launcher AND a one-shot CLI without
installing a second command. MCC-FT-004 adds `search` and `describe` so
users don't need an MCP client to poke the index.

Backward compat is preserved — `tool-compass` with no args (or with the
explicit `serve` subcommand) still starts the gateway server, matching the
pre-CLI behavior users may have wired into Claude Desktop etc.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional


def _build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argparse tree.

    Pulled out of main() so tests can introspect the parser without invoking
    any subcommand side effects.

    FE-A-010: top-level description names every subcommand the user might
    type next, including `ui` (which delegates to `tool-compass-ui` if the
    extras are installed). New users running `tool-compass --help` now have
    a discoverable path to the Gradio surface.

    FE-B-009: every subcommand carries an `epilog` with one curated
    example, per clig.dev (CLI Guidelines) and Heroku CLI style.
    """
    parser = argparse.ArgumentParser(
        prog="tool-compass",
        description=(
            "Tool Compass — semantic MCP tool discovery gateway.\n"
            "\n"
            "With no subcommand, runs the gateway server (default).\n"
            "Subcommands: serve, search, describe, sync, doctor.\n"
            "Web UI: install `tool-compass[ui]` and run `tool-compass-ui`."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  tool-compass                       # run the MCP gateway\n"
            "  tool-compass search 'read a file'  # one-shot search\n"
            "  tool-compass describe bridge:read_file\n"
            "  tool-compass sync                  # rebuild the index\n"
            "  tool-compass doctor                # diagnostics JSON\n"
        ),
    )
    # FE-A-017: catch the wider exception set so a bad regex, syntax error,
    # or import-time side-effect in _version.py does not crash the CLI on
    # first run. The fallback is the same "unknown" string we used before.
    try:
        from _version import __version__ as _tc_version
    except Exception:  # pragma: no cover — defensive fallback
        _tc_version = "unknown"
    parser.add_argument(
        "--version",
        action="version",
        version=f"tool-compass {_tc_version}",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # doctor — environment snapshot (delegates to config.doctor()).
    p_doctor = sub.add_parser(
        "doctor",
        help="Print diagnostic info (config path, backends, Ollama reach)",
        epilog=(
            "Example:\n  tool-compass doctor | jq .config_path"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_doctor.add_argument(
        "--text",
        action="store_true",
        help="Text summary (default emits JSON for jq pipelines).",
    )

    # search — one-shot semantic search against the built index.
    p_search = sub.add_parser(
        "search",
        help="One-shot semantic search (free-text intent)",
        epilog=(
            "Examples:\n"
            "  tool-compass search 'generate an AI image'\n"
            "  tool-compass search 'read a file' --top 3 --json | jq '.[0].tool'\n"
            "\n"
            "If Ollama is unreachable, search falls back to keyword matching."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_search.add_argument(
        "intent",
        type=str,
        help="Free-text description of what you want to do.",
    )
    p_search.add_argument(
        "--top", type=int, default=5,
        help="Maximum number of results to return (default 5; 1-10 valid).",
    )
    p_search.add_argument(
        "--json", action="store_true",
        help="JSON output suitable for jq/script pipelines.",
    )

    # describe — print the schema / metadata for a specific tool.
    p_describe = sub.add_parser(
        "describe",
        help="Print tool schema (parameters, examples, server, category)",
        epilog=(
            "Examples:\n"
            "  tool-compass describe bridge:read_file\n"
            "  tool-compass describe comfy:comfy_generate --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_describe.add_argument(
        "tool_name",
        type=str,
        help="Qualified tool name (e.g., bridge:read_file).",
    )
    p_describe.add_argument(
        "--json", action="store_true",
        help="JSON output (default emits Markdown).",
    )

    # sync — rebuild the index from configured backends.
    p_sync = sub.add_parser(
        "sync",
        help="Rebuild the index from backends (run after config changes)",
        epilog=(
            "Example:\n"
            "  tool-compass sync\n"
            "\n"
            "Idempotent. Reads compass_config.json."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_sync.add_argument(
        "--force",
        action="store_true",
        help=(
            "Force a full rebuild even if no backend changes are detected. "
            "Currently a no-op (full_sync always rebuilds) — reserved for "
            "the incremental-sync path."
        ),
    )

    # serve — explicit form of the default (server launch). Kept separate
    # so `tool-compass --http` still works on the root parser in future.
    p_serve = sub.add_parser(
        "serve",
        help="Run MCP gateway server (default when no subcommand given)",
        epilog="Example:\n  tool-compass serve --http",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_serve.add_argument("--http", action="store_true", help="HTTP transport")

    return parser


def _load_index():
    """Open CompassIndex against the on-disk HNSW + SQLite.

    Returns the loaded index or None if loading failed. Callers print a
    user-facing hint when None so we don't leak RuntimeError tracebacks.
    """
    from indexer import CompassIndex

    index = CompassIndex()
    if not index.load_index():
        return None
    return index


def _cmd_search(args: argparse.Namespace) -> int:
    """Run a one-shot semantic search and print results.

    Text mode is a compact table; --json emits a stable shape suited to
    piping into `jq`. Load-failure is a hint, not a crash — most users
    hitting this path just haven't run `tool-compass sync` yet.
    """
    index = _load_index()
    if index is None:
        print(
            "Index not available. Run `tool-compass sync` to build it.",
            file=sys.stderr,
        )
        return 1

    results = asyncio.run(index.search(args.intent, top_k=args.top))

    if args.json:
        payload = [
            {
                "rank": r.rank,
                "tool": r.tool.name,
                "score": round(r.score, 4),
                "category": r.tool.category,
                "server": r.tool.server,
                "description": r.tool.description,
            }
            for r in results
        ]
        print(json.dumps(payload, indent=2))
        return 0

    if not results:
        # FE-B-010 + Nielsen #9: empty results is an error-adjacent state.
        # State the problem AND suggest the next action; keep exit code 0
        # (an intentional empty result is not a failure).
        print(f"No tools matched intent: {args.intent!r}")
        print(
            "Try a broader intent, lower --top to widen, or run "
            "`tool-compass describe <name>` if you know the tool name.",
            file=sys.stderr,
        )
        return 0

    # Plain-text table — width-tolerant, no external deps.
    print(f"{'rank':<4} {'score':<7} {'tool':<40} description")
    print("-" * 80)
    for r in results:
        name = r.tool.name if len(r.tool.name) <= 40 else r.tool.name[:37] + "..."
        desc = r.tool.description or ""
        if len(desc) > 60:
            desc = desc[:57] + "..."
        print(f"{r.rank:<4} {r.score:<7.3f} {name:<40} {desc}")
    return 0


def _cmd_describe(args: argparse.Namespace) -> int:
    """Print schema + description + examples for a named tool.

    Reads straight from the index's SQLite rather than going through
    CompassIndex.search, because describe is a by-name lookup that should
    not depend on the HNSW being loaded.
    """
    from indexer import SQLITE_DB_PATH

    db_path = Path(SQLITE_DB_PATH)
    if not db_path.exists():
        print(
            f"No tool DB at {db_path}. Run `tool-compass sync` first.",
            file=sys.stderr,
        )
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    suggestions: List[str] = []
    try:
        row = conn.execute(
            "SELECT name, description, category, server, parameters, examples, is_core "
            "FROM tools WHERE name = ?",
            (args.tool_name,),
        ).fetchone()
        # FE-A-018: if no exact match, gather up to 3 substring suggestions
        # so the user is not left on a dead-end "not found". Matches the UI
        # surface's partial-match LIKE path so CLI and UI behave the same.
        if row is None:
            needle = f"%{args.tool_name}%"
            rows = conn.execute(
                "SELECT name FROM tools "
                "WHERE name LIKE ? OR description LIKE ? "
                "ORDER BY (CASE WHEN name LIKE ? THEN 0 ELSE 1 END), name "
                "LIMIT 3",
                (needle, needle, needle),
            ).fetchall()
            suggestions = [r["name"] for r in rows]
    except sqlite3.OperationalError as e:
        print(f"DB query failed: {e}", file=sys.stderr)
        conn.close()
        return 2
    conn.close()

    if row is None:
        print(f"Tool not found: {args.tool_name}", file=sys.stderr)
        if suggestions:
            print("Did you mean:", file=sys.stderr)
            for s in suggestions:
                print(f"  - {s}", file=sys.stderr)
        else:
            print(
                "Run `tool-compass search` with the intent you have in mind "
                "to discover available tools.",
                file=sys.stderr,
            )
        return 1

    parameters = json.loads(row["parameters"]) if row["parameters"] else {}
    examples = json.loads(row["examples"]) if row["examples"] else []

    if args.json:
        payload = {
            "name": row["name"],
            "description": row["description"],
            "category": row["category"],
            "server": row["server"],
            "parameters": parameters,
            "examples": examples,
            "is_core": bool(row["is_core"]),
        }
        print(json.dumps(payload, indent=2))
        return 0

    # Markdown — human-friendly, pipeable into a viewer.
    print(f"# {row['name']}")
    print()
    print(f"**Category:** {row['category']}")
    print(f"**Server:** {row['server']}")
    if row["is_core"]:
        print("**Core:** yes")
    print()
    print("## Description")
    print(row["description"] or "(no description)")
    if parameters:
        print()
        print("## Parameters")
        for pname, ptype in parameters.items():
            print(f"- `{pname}`: {ptype}")
    if examples:
        print()
        print("## Examples")
        for ex in examples:
            print(f"- {ex}")
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    """Rebuild the index from configured backends.

    `--force` is accepted for future compatibility; today SyncManager.full_sync
    always does a full rebuild, so the flag is a no-op but is retained so
    scripts can be written against the documented surface.
    """
    from backend_client_simple import SimpleBackendManager as BackendManager
    from config import load_config
    from indexer import CompassIndex
    from sync_manager import SyncManager

    async def _run() -> int:
        config = load_config()
        if not config.backends:
            print(
                "No backends configured. Edit your compass_config.json "
                "(see `tool-compass doctor` for the path).",
                file=sys.stderr,
            )
            return 1

        backends = BackendManager(config)
        index = CompassIndex()
        # Best-effort load; full_sync will rebuild regardless.
        index.load_index()

        sync = SyncManager(config, index, backends)
        try:
            result = await sync.full_sync()
        finally:
            await backends.disconnect_all()

        print(json.dumps(result, indent=2, default=str))
        return 0

    # `args.force` is deliberately unused today — see docstring. Reference it
    # so linters don't flag the attribute as dead.
    _ = args.force
    return asyncio.run(_run())


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Print diagnostic info.

    FE-A-011: wrap config.doctor() in try/except so a corrupted config or
    transient permission error returns a non-zero exit code with a single
    user-facing line instead of a raw traceback. The error goes to stderr;
    JSON/text payload goes to stdout, keeping the contract pipeline-safe.

    FE-B-018: default is JSON (this is the canonical machine-readable
    diagnostic surface — release-smoke + CI gates consume the JSON form);
    `--text` switches to a compact human-readable summary so terminal
    users aren't forced to install jq.
    """
    try:
        from config import doctor

        payload = doctor()
    except Exception as e:
        print(
            f"Diagnostic check failed: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return 2

    if getattr(args, "text", False):
        # Compact text summary — version, config path, backend count.
        version = payload.get("version", "unknown")
        config_path = payload.get("config_path", "(unknown)")
        backends = payload.get("backends") or {}
        ollama_url = payload.get("ollama_url", "(unset)")
        print(f"tool-compass {version}")
        print(f"config: {config_path}")
        print(f"backends: {len(backends)} configured")
        print(f"ollama:  {ollama_url}")
        return 0

    print(json.dumps(payload, indent=2, default=str))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Top-level CLI dispatch.

    Default behavior (no args, or explicit `serve`) delegates to the gateway
    server so existing `tool-compass` integrations keep working without
    edits. New subcommands short-circuit before touching gateway.

    FE-A-011: every subcommand path is wrapped — unexpected exceptions
    produce a single-line stderr message and exit code 2 (system error)
    instead of leaking a traceback to terminals or log scrapers.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command is None or args.command == "serve":
            # Backward-compat path: legacy behavior was to launch the server.
            from gateway import main as gateway_main

            return gateway_main() or 0
        if args.command == "doctor":
            return _cmd_doctor(args)
        if args.command == "search":
            return _cmd_search(args)
        if args.command == "describe":
            return _cmd_describe(args)
        if args.command == "sync":
            return _cmd_sync(args)
    except KeyboardInterrupt:
        # Standard Unix convention: 128 + SIGINT (2) = 130.
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as e:
        print(
            f"tool-compass {args.command} failed: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return 2

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main() or 0)
