#!/usr/bin/env python3
"""
Tool Compass - Bootstrap Script
Run this to install dependencies and build the index.

Usage:
    python bootstrap.py
"""

import subprocess
import sys
import os


def run(cmd, check=True):
    """Run a command and print output."""
    print(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result


def _ollama_has_model(url, model, timeout=2.0):
    """Return True if Ollama is reachable at ``url`` AND ``model`` is pulled.

    cli-ux-003: replaces the old ``curl -s .../api/tags`` shell-out. Reuses
    config._ollama_reachable for the reachability gate (so OLLAMA_URL +
    credential handling stay consistent with `doctor`), then probes the same
    /api/tags endpoint via httpx to confirm the embedding model is present.
    No curl dependency; works on Windows where curl may be absent from PATH.
    """
    try:
        from config import _ollama_reachable
    except Exception:
        _ollama_reachable = None
    if _ollama_reachable is not None and not _ollama_reachable(url, timeout):
        return False
    try:
        import httpx
    except ImportError:
        # httpx should be installed by step [1/4]; if it isn't, fall back to
        # the reachability bool alone (can't confirm the model without it).
        return _ollama_reachable is not None and _ollama_reachable(url, timeout)
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(f"{url.rstrip('/')}/api/tags")
            return r.status_code == 200 and model in r.text
    except Exception:
        return False


def main():
    print("=" * 60)
    print("TOOL COMPASS SETUP")
    print("=" * 60)

    # Check Python version
    print(f"\n✓ Python {sys.version_info.major}.{sys.version_info.minor}")

    # Install dependencies
    # cli-ux-004: single source of truth is pyproject.toml — `pip install -e .`
    # installs the full, current dependency set (rich, hnswlib, numpy, httpx,
    # …) instead of a hardcoded subset that drifts. We try the plain install
    # first and only retry with --break-system-packages if pip reports a
    # PEP-668 externally-managed-environment error (Debian/Ubuntu), so we
    # don't unconditionally override the protection on every platform.
    print("\n[1/4] Installing dependencies...")
    here = os.path.dirname(os.path.abspath(__file__))
    result = run(f'pip install -e "{here}" -q', check=False)
    if result.returncode != 0 and "externally-managed-environment" in (
        result.stderr or ""
    ):
        print("  Retrying with --break-system-packages (PEP 668 detected)...")
        run(f'pip install -e "{here}" --break-system-packages -q')
    elif result.returncode != 0:
        sys.exit(result.returncode)
    print("✓ Dependencies installed")

    # Check Ollama
    # cli-ux-003: reuse the real probe from config so we respect OLLAMA_URL
    # and have no curl-on-PATH dependency (curl is not guaranteed on Windows).
    print("\n[2/4] Checking Ollama...")
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    if not _ollama_has_model(ollama_url, "nomic-embed-text"):
        print(
            f"⚠ Ollama not reachable at {ollama_url}, or "
            "nomic-embed-text not available"
        )
        print("  Please run: ollama pull nomic-embed-text")
        print("  Then re-run this script")
        sys.exit(1)
    print("✓ Ollama ready with nomic-embed-text")

    # Build index
    print("\n[3/4] Building Tool Compass index...")
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    run("python indexer.py")
    print("✓ Index built")

    # Run tests
    print("\n[4/4] Running tests...")
    run("python gateway.py --test")

    print("\n" + "=" * 60)
    print("SETUP COMPLETE!")
    print("=" * 60)
    print("\nTo start the server:")
    print("  python gateway.py")
    print("\nTo use with Claude Desktop, add to config:")
    print("""
{
  "mcpServers": {
    "tool-compass": {
      "command": "python",
      "args": ["/path/to/tool-compass/gateway.py"]
    }
  }
}
""")


if __name__ == "__main__":
    main()
