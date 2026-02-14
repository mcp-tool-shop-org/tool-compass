"""Single source of truth for the tool-compass version at runtime.

Reads from importlib.metadata when installed as a package (pip install).
Falls back to pyproject.toml parsing for editable / development installs.
"""

from __future__ import annotations


def _get_version() -> str:
    """Resolve version string, never raises."""
    # 1. Try installed package metadata (works after pip install)
    try:
        from importlib.metadata import version

        return version("tool-compass")
    except Exception:
        pass

    # 2. Fallback: read pyproject.toml from repo root
    try:
        from pathlib import Path
        import re

        pyproject = Path(__file__).parent / "pyproject.toml"
        if pyproject.exists():
            match = re.search(
                r'^version\s*=\s*"([^"]+)"',
                pyproject.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
            if match:
                return match.group(1)
    except Exception:
        pass

    return "0.0.0"


__version__: str = _get_version()
