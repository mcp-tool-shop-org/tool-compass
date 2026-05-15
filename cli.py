"""Tool Compass — CLI entry point.

MCC-FT-001: subcommand shell that subsumes the old `gateway:main` entry so
`tool-compass` can be both a server launcher AND a one-shot CLI without
installing a second command. MCC-FT-004 adds `search` and `describe` so
users don't need an MCP client to poke the index.

Backward compat is preserved — `tool-compass` with no args (or with the
explicit `serve` subcommand) still starts the gateway server, matching the
pre-CLI behavior users may have wired into Claude Desktop etc.

Stage D polish (SD-CLI-001..007) added on top of the v2.2.x argparse spine:

- Color discipline (4 colors max: green/red/yellow/dim) with isatty +
  NO_COLOR + TERM=dumb + --no-color detection (`_should_color`).
- `--json` flag everywhere a script might consume the output (doctor/search/
  describe already had it; sync gains a stable JSON shape).
- Rich `Progress` spinners on doctor + sync TEXT mode only — JSON mode
  prints pure JSON to stdout with zero decorations (script-composability).
- Error rewriting: expected exceptions (FileNotFoundError, ConnectionError,
  JSONDecodeError, sqlite3.OperationalError) get a one-line `_print_error`
  with an actionable hint instead of a raw traceback.
- Exit-code audit: 0 success / 1 expected failure (index missing, backend
  down, tool not found) / 2 usage error (bad flag, missing arg) / 130 SIGINT.
- `--version` lives on the root parser only — argparse propagates it to the
  invocation context so `tool-compass --version` works regardless of the
  selected subcommand (tested by test_version.py via _version import).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, List, Optional


# =============================================================================
# Stage D polish helpers — color, output, error
# =============================================================================


# 4-color discipline (clig.dev "Use color with intention"). Mapped to Rich
# style strings; the `_make_console` factory honors NO_COLOR / TTY / dumb-term.
_C_SUCCESS = "green"
_C_ERROR = "red"
_C_WARN = "yellow"
_C_DIM = "dim"


def _should_color(stream, no_color_flag: bool = False) -> bool:
    """Decide whether to emit ANSI color on a given stream.

    Honors the de-facto cross-tool conventions:

    - ``--no-color`` flag (passed in here as ``no_color_flag``)
    - ``NO_COLOR`` env var (any non-empty value disables — https://no-color.org)
    - ``TERM=dumb`` (legacy terminal that does not handle ANSI)
    - Non-TTY stream (piped to a file or another command — never colorize)

    Returns True only when all four checks allow color. Callers funnel this
    through ``_make_console`` so every Rich Console in the CLI uses the same
    rule.
    """
    if no_color_flag:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    # ``isatty`` may be missing on captured streams (pytest's capsys). Treat
    # missing-isatty as "no" — capsys is by definition not a real terminal.
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except Exception:
        return False


def _make_console(*, stderr: bool = False, no_color_flag: bool = False):
    """Construct a Rich Console honoring the color-discipline rules.

    Returns a Rich ``Console`` if ``rich`` is importable, else a small shim
    that exposes ``.print()`` / ``.status()`` so callers don't need to branch.
    The shim never adds color and never blocks on an animated spinner.
    """
    stream = sys.stderr if stderr else sys.stdout
    use_color = _should_color(stream, no_color_flag=no_color_flag)
    try:
        from rich.console import Console
    except ImportError:  # pragma: no cover — rich is a hard dep, but defensive
        return _PlainConsole(stderr=stderr)
    return Console(
        stderr=stderr,
        force_terminal=use_color or None,  # None => Rich auto-detects
        no_color=not use_color,
        # Wider default than 80 so long tool descriptions don't wrap awkwardly
        # when the user is piping into `less -R`.
        width=None,
        highlight=False,
        # markup=True always — Rich strips markup tags into plain text when
        # no_color=True, but if markup=False it emits the raw "[green]" text
        # literally. Tests + non-TTY callers rely on the markup-stripping path.
        markup=True,
        emoji=False,
        legacy_windows=False,
    )


class _PlainConsole:
    """Fallback Console used if rich isn't importable. Stdout-only, no color.

    Behaves like a thin shim over ``print``. Used in pragma:no-cover paths
    (rich is a declared dependency) but kept so a stripped install does not
    crash the CLI hard.
    """

    def __init__(self, *, stderr: bool = False) -> None:
        self._stream = sys.stderr if stderr else sys.stdout

    def print(self, *objects, **_kwargs) -> None:
        msg = " ".join(str(o) for o in objects)
        # Strip Rich markup like [green]ok[/green] so the user does not see
        # raw tags when running without rich.
        import re

        msg = re.sub(r"\[/?[a-zA-Z0-9_ #]+\]", "", msg)
        print(msg, file=self._stream)

    def status(self, message, **_kwargs):  # pragma: no cover - shim
        return _NullStatus()


class _NullStatus:
    """No-op status used by ``_PlainConsole.status`` to keep call-sites uniform."""

    def __enter__(self):  # pragma: no cover - shim
        return self

    def __exit__(self, *_args):  # pragma: no cover - shim
        return False

    def update(self, *_args, **_kwargs):  # pragma: no cover - shim
        return None


def _print_error(
    console,
    msg: str,
    *,
    hint: Optional[str] = None,
    exit_code: int = 1,
) -> int:
    """Print a uniform error line (red ✗) and optional dim hint, return exit code.

    Implements the clig.dev "Catch errors and rewrite them for humans" pattern:
    a single readable sentence on stderr, optionally followed by a dim
    next-action hint. Callers ``return _print_error(...)`` so exit codes
    bubble up unchanged.
    """
    console.print(f"[{_C_ERROR}]✗[/{_C_ERROR}] {msg}")
    if hint:
        console.print(f"  [{_C_DIM}]› {hint}[/{_C_DIM}]")
    return exit_code


def _print_warn(console, msg: str, *, hint: Optional[str] = None) -> None:
    """Print a yellow ⚠ warning line on the supplied console."""
    console.print(f"[{_C_WARN}]⚠[/{_C_WARN}] {msg}")
    if hint:
        console.print(f"  [{_C_DIM}]› {hint}[/{_C_DIM}]")


def _print_success(console, msg: str) -> None:
    """Print a green ✓ success line on the supplied console."""
    console.print(f"[{_C_SUCCESS}]✓[/{_C_SUCCESS}] {msg}")


def _print_dim(console, msg: str) -> None:
    """Print a dim grey hint line on the supplied console."""
    console.print(f"[{_C_DIM}]{msg}[/{_C_DIM}]")


# =============================================================================
# Argparse parser — unchanged shape, with --no-color + --json on `sync`
# =============================================================================


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

    SD-CLI-001: ``--no-color`` lives on the root parser so users can disable
    ANSI globally even when wrapping the CLI from a non-interactive harness
    that exposes ``isatty()`` (rare, but it happens with some CI runners).
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
            "\n"
            "Color is on by default in interactive terminals. Disable via\n"
            "`--no-color`, NO_COLOR=1, or TERM=dumb. Output piped to a file\n"
            "or another command is never colored."
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
    # SD-CLI-001: --no-color flag on the root parser. argparse forwards it to
    # every subcommand via the shared Namespace so subparsers don't need to
    # redeclare it.
    parser.add_argument(
        "--no-color",
        action="store_true",
        dest="no_color",
        help=(
            "Disable ANSI color even on a TTY. Same effect as NO_COLOR=1 "
            "or TERM=dumb. Output piped to a file or another command is "
            "never colored regardless of this flag."
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # doctor — environment snapshot (delegates to config.doctor()).
    p_doctor = sub.add_parser(
        "doctor",
        help="Print diagnostic info (config path, backends, Ollama reach)",
        epilog=(
            "Examples:\n"
            "  tool-compass doctor              # JSON for jq pipelines (default)\n"
            "  tool-compass doctor --text       # human-readable summary\n"
            "  tool-compass doctor | jq .config_path\n"
            "\n"
            "JSON fields: version, python_version, platform, config_path,\n"
            "config, base_path, data_dir, index_path, index_exists,\n"
            "index_size_bytes, analytics_db_path, ollama_url,\n"
            "ollama_reachable, deprecated_tools."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_doctor.add_argument(
        "--text",
        action="store_true",
        help="Text summary (default emits JSON for jq pipelines).",
    )
    # SD-CLI-002: explicit --json flag is a no-op aliasing the default, but
    # documenting it makes pipelines self-explanatory ("tool-compass doctor
    # --json" reads better than depending on an implicit default).
    p_doctor.add_argument(
        "--json",
        action="store_true",
        dest="json",
        help=(
            "Emit JSON (default). Explicit form for self-documenting pipelines."
        ),
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
            "Examples:\n"
            "  tool-compass sync                # rebuild and print summary\n"
            "  tool-compass sync --json | jq .  # script-friendly output\n"
            "\n"
            "Idempotent. Reads compass_config.json. JSON shape mirrors the\n"
            "internal sync result (tools_added/updated/removed, duration, errors)."
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
    # SD-CLI-002: surface --json for sync. Default mode prints a Rich-colored
    # human summary with a spinner; --json strips all decoration and prints
    # the raw sync result for scripts.
    p_sync.add_argument(
        "--json",
        action="store_true",
        help="JSON output suitable for jq/script pipelines.",
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


def _no_color(args: argparse.Namespace) -> bool:
    """True if the user passed --no-color (or argparse never set the attribute)."""
    return bool(getattr(args, "no_color", False))


# =============================================================================
# Subcommand handlers — text-mode polish layered on; JSON mode unchanged
# =============================================================================


def _cmd_search(args: argparse.Namespace) -> int:
    """Run a one-shot semantic search and print results.

    Text mode is a Rich-colored compact table; --json emits a stable shape
    suited to piping into `jq`. Load-failure is a hint, not a crash — most
    users hitting this path just haven't run `tool-compass sync` yet.

    SD-CLI-005: index-missing now produces a one-line ``_print_error`` with
    an actionable hint, not a flat "Index not available." sentence.
    SD-CLI-006: exit code 1 reserved for expected failures (index missing,
    empty results). Crashes still surface as exit 2 via the top-level
    ``main`` wrapper.
    """
    err_console = _make_console(stderr=True, no_color_flag=_no_color(args))
    out_console = _make_console(no_color_flag=_no_color(args))

    index = _load_index()
    if index is None:
        return _print_error(
            err_console,
            "Index not available.",
            hint="Run `tool-compass sync` to build it.",
            exit_code=1,
        )

    try:
        results = asyncio.run(index.search(args.intent, top_k=args.top))
    except (ConnectionError, OSError) as e:
        return _print_error(
            err_console,
            f"Search failed: {e}",
            hint=(
                "Ollama may be unreachable. Run `tool-compass doctor` to "
                "confirm and check `ollama serve` is running."
            ),
            exit_code=1,
        )

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
        # SD-CLI-002: --json output goes to stdout with zero decoration so
        # `tool-compass search ... --json | jq` works without `2>/dev/null`.
        print(json.dumps(payload, indent=2))
        return 0

    if not results:
        # FE-B-010 + Nielsen #9: empty results is an error-adjacent state.
        # State the problem AND suggest the next action; keep exit code 0
        # (an intentional empty result is not a failure).
        out_console.print(f"No tools matched intent: {args.intent!r}")
        _print_dim(
            err_console,
            "› Try a broader intent, lower --top to widen, or run "
            "`tool-compass describe <name>` if you know the tool name.",
        )
        return 0

    # Plain-text table — Rich-styled. Header dim, score column green where
    # it's a high-confidence match (>= 0.7) so users can eyeball the spread.
    header = f"{'rank':<4} {'score':<7} {'tool':<40} description"
    out_console.print(f"[{_C_DIM}]{header}[/{_C_DIM}]")
    out_console.print(f"[{_C_DIM}]{'-' * 80}[/{_C_DIM}]")
    for r in results:
        name = r.tool.name if len(r.tool.name) <= 40 else r.tool.name[:37] + "..."
        desc = r.tool.description or ""
        if len(desc) > 60:
            desc = desc[:57] + "..."
        score_color = _C_SUCCESS if r.score >= 0.7 else _C_DIM
        out_console.print(
            f"{r.rank:<4} "
            f"[{score_color}]{r.score:<7.3f}[/{score_color}] "
            f"{name:<40} {desc}"
        )
    return 0


def _cmd_describe(args: argparse.Namespace) -> int:
    """Print schema + description + examples for a named tool.

    Reads straight from the index's SQLite rather than going through
    CompassIndex.search, because describe is a by-name lookup that should
    not depend on the HNSW being loaded.

    SD-CLI-005: missing DB and unknown-tool both rewritten as `_print_error`
    with hints. Exit codes: 1 for "expected" (DB missing, tool not found),
    2 for usage (a DB query that fails to parse the schema).
    """
    err_console = _make_console(stderr=True, no_color_flag=_no_color(args))
    out_console = _make_console(no_color_flag=_no_color(args))

    from indexer import SQLITE_DB_PATH

    db_path = Path(SQLITE_DB_PATH)
    if not db_path.exists():
        return _print_error(
            err_console,
            f"No tool DB at {db_path}.",
            hint="Run `tool-compass sync` first to build the index.",
            exit_code=1,
        )

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
        conn.close()
        return _print_error(
            err_console,
            f"DB query failed: {e}",
            hint=(
                "The tool index may be corrupted. Try `tool-compass sync` "
                "to rebuild it."
            ),
            exit_code=2,
        )
    conn.close()

    if row is None:
        # Build a hint that includes suggestions when we have them.
        if suggestions:
            hint = "Did you mean: " + ", ".join(suggestions)
        else:
            hint = (
                "Run `tool-compass search` with the intent you have in mind "
                "to discover available tools."
            )
        return _print_error(
            err_console,
            f"Tool not found: {args.tool_name}",
            hint=hint,
            exit_code=1,
        )

    try:
        parameters = json.loads(row["parameters"]) if row["parameters"] else {}
        examples = json.loads(row["examples"]) if row["examples"] else []
    except json.JSONDecodeError as e:
        # SD-CLI-005: a malformed schema in the DB used to crash with a raw
        # traceback. Rewrite it so the user sees the path they should
        # rebuild from.
        return _print_error(
            err_console,
            f"Tool schema malformed for {args.tool_name}: {e}",
            hint="Run `tool-compass sync` to rebuild the index.",
            exit_code=2,
        )

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

    # Markdown — human-friendly, pipeable into a viewer. Headings get the
    # green ✓ accent so colored terminals can scan structure at a glance;
    # uncolored output stays plain Markdown.
    out_console.print(f"[bold]# {row['name']}[/bold]")
    out_console.print()
    out_console.print(f"[{_C_DIM}]**Category:**[/{_C_DIM}] {row['category']}")
    out_console.print(f"[{_C_DIM}]**Server:**[/{_C_DIM}] {row['server']}")
    if row["is_core"]:
        out_console.print(f"[{_C_SUCCESS}]**Core:** yes[/{_C_SUCCESS}]")
    out_console.print()
    out_console.print("[bold]## Description[/bold]")
    out_console.print(row["description"] or "(no description)")
    if parameters:
        out_console.print()
        out_console.print("[bold]## Parameters[/bold]")
        for pname, ptype in parameters.items():
            out_console.print(f"- `{pname}`: {ptype}")
    if examples:
        out_console.print()
        out_console.print("[bold]## Examples[/bold]")
        for ex in examples:
            out_console.print(f"- {ex}")
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    """Rebuild the index from configured backends.

    `--force` is accepted for future compatibility; today SyncManager.full_sync
    always does a full rebuild, so the flag is a no-op but is retained so
    scripts can be written against the documented surface.

    SD-CLI-003: text mode shows a Rich spinner while the rebuild runs (the
    underlying sync is opaque to us — there's no per-backend progress event
    surface yet). JSON mode (``--json``) prints the raw sync result with
    zero decoration. We keep the legacy "print full JSON to stdout" behavior
    behind the flag so existing scripts pipe through unchanged.
    SD-CLI-005: a config without backends now emits ``_print_error`` with a
    hint pointing at the config path. ``ConnectionError`` and
    ``FileNotFoundError`` from the sync path are caught and rewritten.
    """
    err_console = _make_console(stderr=True, no_color_flag=_no_color(args))
    out_console = _make_console(no_color_flag=_no_color(args))
    json_mode = bool(getattr(args, "json", False))

    from backend_client_simple import SimpleBackendManager as BackendManager
    from config import load_config
    from indexer import CompassIndex
    from sync_manager import SyncManager

    async def _run() -> tuple[int, Optional[dict[str, Any]]]:
        config = load_config()
        if not config.backends:
            _print_error(
                err_console,
                "No backends configured.",
                hint=(
                    "Edit your compass_config.json "
                    "(see `tool-compass doctor` for the resolved path)."
                ),
                exit_code=1,
            )
            return 1, None

        backends = BackendManager(config)
        index = CompassIndex()
        # Best-effort load; full_sync will rebuild regardless.
        index.load_index()

        sync = SyncManager(config, index, backends)
        try:
            result = await sync.full_sync()
        finally:
            await backends.disconnect_all()

        return 0, result

    # `args.force` is deliberately unused today — see docstring. Reference it
    # so linters don't flag the attribute as dead.
    _ = args.force

    try:
        # JSON mode: no spinner (decorations on stdout would corrupt the
        # script-composable shape). Text mode: spinner around the work, then
        # a colored summary on stdout.
        if json_mode:
            rc, result = asyncio.run(_run())
            if result is not None:
                print(json.dumps(result, indent=2, default=str))
            return rc

        # Text mode — Rich Progress with a Spinner column. ``transient=True``
        # means the spinner disappears once work finishes, leaving the
        # terminal clean for the summary lines below.
        try:
            from rich.progress import Progress, SpinnerColumn, TextColumn

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=err_console,  # spinner on stderr so stdout stays clean
                transient=True,
            ) as progress:
                task = progress.add_task(
                    "Rebuilding tool index from backends...",
                    total=None,
                )
                rc, result = asyncio.run(_run())
                progress.update(task, completed=True)
        except ImportError:  # pragma: no cover — rich is a hard dep
            rc, result = asyncio.run(_run())

        if rc != 0 or result is None:
            return rc

        # Summary lines — colored highlights of the key counts. Falls back to
        # the raw JSON if the result shape changes underneath us so users
        # never see "(none)" misleading output.
        added = result.get("tools_added", 0)
        updated = result.get("tools_updated", 0)
        removed = result.get("tools_removed", 0)
        duration = result.get("duration_seconds") or result.get("duration", "?")
        errors = result.get("errors") or []

        _print_success(out_console, f"Sync complete in {duration}s.")
        out_console.print(
            f"  [{_C_SUCCESS}]+{added}[/{_C_SUCCESS}] added  "
            f"[{_C_DIM}]~{updated}[/{_C_DIM}] updated  "
            f"[{_C_WARN}]-{removed}[/{_C_WARN}] removed"
        )
        if errors:
            _print_warn(
                err_console,
                f"{len(errors)} backend error(s) — see compass logs",
                hint="Run `tool-compass doctor` to inspect backend health.",
            )
        return rc
    except FileNotFoundError as e:
        return _print_error(
            err_console,
            f"Required file missing: {e}",
            hint="Run `tool-compass doctor` to confirm config + index paths.",
            exit_code=1,
        )
    except ConnectionError as e:
        return _print_error(
            err_console,
            f"Backend connection failed: {e}",
            hint=(
                "Check `tool-compass doctor` for backend health and confirm "
                "the configured server commands are runnable."
            ),
            exit_code=1,
        )


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

    SD-CLI-003: text mode now shows a Rich spinner per logical check
    (config load, version probe, Ollama reach). JSON mode preserves the
    pre-Stage-D behavior exactly — pure JSON to stdout, no decorations
    (tests parse the JSON directly, so any spinner output would break them).
    SD-CLI-004: text mode summary uses the 4-color discipline: green ✓ for
    "ollama reachable" and "config loaded", yellow ⚠ for "ollama down",
    dim grey for paths.
    """
    err_console = _make_console(stderr=True, no_color_flag=_no_color(args))
    out_console = _make_console(no_color_flag=_no_color(args))
    text_mode = bool(getattr(args, "text", False))

    try:
        if text_mode:
            # Spinner only in text mode — JSON callers must see pure JSON.
            try:
                from rich.progress import Progress, SpinnerColumn, TextColumn

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=err_console,
                    transient=True,
                ) as progress:
                    task = progress.add_task(
                        "Collecting diagnostics...",
                        total=None,
                    )
                    from config import doctor

                    payload = doctor()
                    progress.update(task, completed=True)
            except ImportError:  # pragma: no cover — rich is a hard dep
                from config import doctor

                payload = doctor()
        else:
            from config import doctor

            payload = doctor()
    except FileNotFoundError as e:
        return _print_error(
            err_console,
            f"Diagnostic check failed — config file missing: {e}",
            hint=(
                "Edit compass_config.json (see CONTRIBUTING.md for the schema)."
            ),
            exit_code=2,
        )
    except json.JSONDecodeError as e:
        return _print_error(
            err_console,
            f"Diagnostic check failed — config JSON is malformed: {e}",
            hint=(
                "Validate compass_config.json with `python -m json.tool` and "
                "re-run `tool-compass doctor`."
            ),
            exit_code=2,
        )
    except Exception as e:
        return _print_error(
            err_console,
            f"Diagnostic check failed: {type(e).__name__}: {e}",
            exit_code=2,
        )

    if text_mode:
        # Compact text summary — version, config path, backend count, ollama
        # health. Each line colored per the 4-color discipline so the user
        # can eyeball "what's wrong" without re-reading the JSON.
        version = payload.get("version", "unknown")
        config_path = payload.get("config_path", "(unknown)")
        backends = payload.get("backends") or payload.get("config", {}).get(
            "backends"
        ) or {}
        ollama_url = payload.get("ollama_url", "(unset)")
        ollama_ok = payload.get("ollama_reachable", False)
        index_exists = payload.get("index_exists", False)

        out_console.print(f"[bold]tool-compass {version}[/bold]")
        out_console.print(f"  [{_C_DIM}]config:[/{_C_DIM}] {config_path}")
        # Backend count works for both dict-of-backends and list shapes.
        if isinstance(backends, (list, tuple)):
            backend_count = len(backends)
        elif isinstance(backends, dict):
            backend_count = len(backends)
        else:
            backend_count = 0
        out_console.print(
            f"  [{_C_DIM}]backends:[/{_C_DIM}] {backend_count} configured"
        )
        if ollama_ok:
            _print_success(out_console, f"ollama reachable at {ollama_url}")
        else:
            _print_warn(
                out_console,
                f"ollama unreachable at {ollama_url}",
                hint="Run `ollama serve` or set OLLAMA_URL.",
            )
        if index_exists:
            _print_success(out_console, "tool index present")
        else:
            _print_warn(
                out_console,
                "tool index missing",
                hint="Run `tool-compass sync` to build the index.",
            )
        return 0

    # SD-CLI-002: JSON mode — pure JSON on stdout. Tests parse this directly.
    print(json.dumps(payload, indent=2, default=str))
    return 0


# =============================================================================
# Top-level dispatch
# =============================================================================


def main(argv: Optional[List[str]] = None) -> int:
    """Top-level CLI dispatch.

    Default behavior (no args, or explicit `serve`) delegates to the gateway
    server so existing `tool-compass` integrations keep working without
    edits. New subcommands short-circuit before touching gateway.

    FE-A-011 / SD-CLI-005: every subcommand path is wrapped — unexpected
    exceptions produce a single-line ``_print_error`` and exit code 2 (system
    error / usage) instead of leaking a traceback to terminals or log scrapers.

    SD-CLI-006 exit-code audit:
        0   success
        1   expected failure (index missing, tool not found, backend down)
        2   usage error / unexpected internal exception
        130 SIGINT (Unix convention: 128 + signal number)
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    err_console = _make_console(stderr=True, no_color_flag=_no_color(args))

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
        err_console.print(
            f"\n[{_C_WARN}]Interrupted.[/{_C_WARN}]"
        )
        return 130
    except Exception as e:
        return _print_error(
            err_console,
            f"tool-compass {args.command} failed: {type(e).__name__}: {e}",
            exit_code=2,
        )

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main() or 0)
