#!/usr/bin/env python3
"""
Tool Compass - Bootstrap Script
Run this to install dependencies and build the index.

Usage:
    python bootstrap.py
"""

import json
import os
import subprocess
import sys


# Providers that speak Ollama's /api/tags + pull contract.
_OLLAMA_PROVIDERS = frozenset({"ollama", ""})
# Non-Ollama providers must not be gated on nomic-embed-text in /api/tags.
_REMOTE_PROVIDERS = frozenset({"openai", "openai-compatible", "local"})


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


def run_python(script, *script_args, check=True):
    """Invoke a repo script with this interpreter, never a bare ``python``.

    F-1a138aee: Windows PATH may not have ``python``, and a different
    interpreter could miss the just-installed editable package.
    """
    argv = [sys.executable, script, *script_args]
    print("$ " + " ".join(argv))
    result = subprocess.run(argv, capture_output=True, text=True)
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
            if r.status_code != 200:
                return False
            body = r.text or ""
            # Prefer structured names (model or model:tag) over a raw substring.
            try:
                payload = r.json()
                names = [
                    (m.get("name") or m.get("model") or "")
                    for m in (payload.get("models") or [])
                    if isinstance(m, dict)
                ]
                if names:
                    return any(
                        n == model
                        or n == f"{model}:latest"
                        or n.startswith(f"{model}:")
                        for n in names
                    )
            except Exception:
                pass
            return model in body
    except Exception:
        return False


def _embedding_endpoint_reachable(url, timeout=2.0):
    """True if ``url`` answers HTTP. HEAD first (not billed); GET fallback.

    F-1a138aee: openai / openai-compatible must not POST /v1/embeddings
    during first-run (that can incur usage). Any response, including 401/404,
    means the host is up.
    """
    if not url:
        return False
    try:
        import httpx
    except ImportError:
        try:
            from config import _http_reachable

            return _http_reachable(url, timeout)
        except Exception:
            return False
    target = url.rstrip("/")
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            try:
                r = client.head(target)
                # 405 = method not allowed, still a live server.
                if r.status_code < 500 or r.status_code == 405:
                    return True
            except Exception:
                pass
            client.get(target)
            return True
    except Exception:
        return False


def _raw_provider_from_config_file():
    """Read embedding_provider from the on-disk JSON without clamping.

    CompassConfig.validate_and_clamp maps unknown names (including
    ``local``) to ollama. Bootstrap must honor the file/env spelling so
    an openai/local operator is not forced through /api/tags.
    """
    try:
        from config import get_config_path

        path = get_config_path()
        if not path.exists():
            return ""
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("embedding_provider")
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    except Exception:
        pass
    return ""


def _bootstrap_embedding_settings():
    """Resolve provider/model/URLs from env, then CompassConfig.

    Precedence for provider: TOOL_COMPASS_EMBEDDING_PROVIDER > raw config
    file > CompassConfig.embedding_provider > ollama.
    """
    env_provider = os.environ.get("TOOL_COMPASS_EMBEDDING_PROVIDER", "").strip().lower()
    model = "nomic-embed-text"
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    base_url = ollama_url
    cfg_provider = ""
    try:
        from config import load_config

        cfg = load_config()
        cfg_provider = (getattr(cfg, "embedding_provider", None) or "").strip().lower()
        model = getattr(cfg, "embedding_model", None) or model
        ollama_url = getattr(cfg, "ollama_url", None) or ollama_url
        try:
            base_url = cfg.resolved_embedding_base_url()
        except Exception:
            base_url = getattr(cfg, "embedding_base_url", None) or ollama_url
    except Exception:
        pass
    provider = env_provider or _raw_provider_from_config_file() or cfg_provider or "ollama"
    if not base_url:
        base_url = ollama_url
    return provider, model, base_url, ollama_url


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

    # F-1a138aee: provider-aware first-run. Do not hard-exit on Ollama
    # /api/tags + nomic-embed-text when embedding_provider is openai /
    # openai-compatible / local. Load CompassConfig (or
    # TOOL_COMPASS_EMBEDDING_PROVIDER) before the gate.
    provider, model, base_url, ollama_url = _bootstrap_embedding_settings()
    print(f"\n[2/4] Checking embeddings ({provider})...")
    if provider in _OLLAMA_PROVIDERS:
        if not _ollama_has_model(ollama_url, model):
            print(
                f"⚠ Ollama not reachable at {ollama_url}, or "
                f"{model} not available"
            )
            print(f"  Please run: ollama pull {model}")
            print("  Then re-run this script")
            sys.exit(1)
        print(f"✓ Ollama ready with {model}")
    else:
        if not _embedding_endpoint_reachable(base_url):
            print(
                f"⚠ Embedding provider {provider!r} not reachable at {base_url}"
            )
            print("  Set embedding_base_url in compass_config.json")
            print(
                "  For openai / openai-compatible, set "
                "TOOL_COMPASS_EMBEDDING_API_KEY (see .env.example)"
            )
            sys.exit(1)
        print(f"✓ {provider} embeddings reachable at {base_url}")

    # Build index
    print("\n[3/4] Building Tool Compass index...")
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    run_python("indexer.py")
    print("✓ Index built")

    # Run tests
    print("\n[4/4] Running tests...")
    run_python("gateway.py", "--test")

    print("\n" + "=" * 60)
    print("SETUP COMPLETE!")
    print("=" * 60)
    print("\nTo start the server:")
    print("  tool-compass serve")
    print("\nTo use with Claude Desktop, add to config:")
    print("""
{
  "mcpServers": {
    "tool-compass": {
      "command": "npx",
      "args": ["-y", "@mcptoolshop/tool-compass", "serve"]
    }
  }
}
""")


if __name__ == "__main__":
    main()
