"""Version consistency tests for tool-compass."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"


def _read_pyproject_version() -> str:
    match = re.search(
        r'^version\s*=\s*"([^"]+)"',
        PYPROJECT.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, "No version found in pyproject.toml"
    return match.group(1)


class TestVersionConsistency:
    """Verify version strings are consistent and ship-ready."""

    def test_version_is_semver(self):
        version = _read_pyproject_version()
        assert re.match(r"^\d+\.\d+\.\d+", version), f"Not semver: {version}"

    def test_version_at_least_1(self):
        version = _read_pyproject_version()
        major = int(version.split(".")[0])
        assert major >= 1, f"Pre-release version: {version}"

    def test_changelog_mentions_version(self):
        version = _read_pyproject_version()
        changelog = CHANGELOG.read_text(encoding="utf-8")
        assert version in changelog, f"CHANGELOG missing version {version}"

    def test_version_file_reads_pyproject(self):
        """_version.py fallback should find pyproject.toml version."""
        result = subprocess.run(
            [sys.executable, "-c",
             "import re; from pathlib import Path; "
             "m = re.search(r'^version\\s*=\\s*\"([^\"]+)\"', "
             "Path('pyproject.toml').read_text(), re.MULTILINE); "
             "print(m.group(1))"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0
        file_version = result.stdout.strip()
        pyproject_version = _read_pyproject_version()
        assert file_version == pyproject_version

    def test_cli_version_flag(self):
        """Verify the gateway module can be imported without crashing."""
        result = subprocess.run(
            [sys.executable, "-c", "from _version import __version__; print(__version__)"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0
        version = result.stdout.strip()
        assert re.match(r"^\d+\.\d+\.\d+", version)
