"""
Tool Compass - Configuration Schema
Defines how backends are configured and connected.

Environment Variables:
    TOOL_COMPASS_BASE_PATH: Base path for the project (default: parent of tool_compass)
    TOOL_COMPASS_PYTHON: Path to Python executable (default: auto-detect from venv)
    TOOL_COMPASS_CONFIG: Path to config file (default: <user_config_dir>/compass_config.json)
    TOOL_COMPASS_DATA_DIR: Override user data directory (default: platform-specific)
    OLLAMA_URL: Ollama server URL (default: http://localhost:11434)

Default config directories by platform:
    Windows: %LOCALAPPDATA%/tool-compass/
    macOS: ~/Library/Application Support/tool-compass/
    Linux: ~/.config/tool-compass/ (or $XDG_CONFIG_HOME/tool-compass/)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Literal
from pathlib import Path
import json
import logging
import os
import platform as _platform
import shutil
import sys
import re
import time
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)


@dataclass
class StdioBackend:
    """Backend that spawns an MCP server as subprocess."""

    type: Literal["stdio"] = "stdio"
    command: str = ""
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None


@dataclass
class HttpBackend:
    """Backend that connects to an MCP server over HTTP/SSE."""

    type: Literal["http"] = "http"
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0


@dataclass
class ImportBackend:
    """Backend that imports an MCP server module directly (same process)."""

    type: Literal["import"] = "import"
    module: str = ""
    server_var: str = "mcp"  # Variable name of the FastMCP instance


BackendConfig = StdioBackend | HttpBackend | ImportBackend


@dataclass
class CompassConfig:
    """Full Tool Compass configuration."""

    # Backend server connections
    backends: Dict[str, BackendConfig] = field(default_factory=dict)

    # Embedding settings
    embedding_model: str = "nomic-embed-text"
    ollama_url: str = "http://localhost:11434"

    # Index settings
    index_dir: str = "./db"
    auto_sync: bool = True  # Auto-discover tools from backends on startup

    # Search settings
    default_top_k: int = 5
    min_confidence: float = 0.3

    # Progressive disclosure (reduces tokens further)
    progressive_disclosure: bool = True

    # Sync settings
    sync_check_on_startup: bool = True
    sync_polling_interval: int = 300  # seconds, 0 = disabled

    # Analytics settings
    analytics_enabled: bool = True
    hot_cache_size: int = 10

    # Chain detection settings
    chain_indexing_enabled: bool = True
    chain_detection_min_occurrences: int = 3
    top_chains_cache_size: int = 5

    # Circuit breaker / retry tuning (BE-B-014). Promoted from module-level
    # constants in embedder.py so operators can tune without code edits.
    # Ranges clamped in validate_and_clamp() to keep the behavior sane.
    ollama_breaker_failure_threshold: int = 3
    ollama_breaker_open_seconds: float = 30.0
    ollama_retry_attempts: int = 3
    ollama_retry_backoffs: List[float] = field(
        default_factory=lambda: [0.5, 1.0, 2.0]
    )

    # HNSW parameters (BE-B-008). Promoted from module-level constants in
    # indexer.py so operators can re-tune at scale without forking.
    hnsw_m: int = 16
    hnsw_ef_construction: int = 200
    hnsw_ef_search: int = 50

    @classmethod
    def from_file(cls, path: Path) -> "CompassConfig":
        """Load config from JSON file with variable substitution.

        On corrupt/unreadable config (MCC-B-001 + BE-A-006), MOVES the bad
        file aside (rather than copy) so repeated load_config() calls don't
        spawn a new .bak.<ts> on every restart. The user gets a single,
        durable rescue copy and an actionable log line.
        """
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            # BE-A-006: use a deterministic sentinel name (single .bak suffix)
            # so the backup count stays at 1 regardless of restart count. We
            # only stamp a timestamp if the .bak slot is already taken (to
            # preserve the FIRST corruption, which is usually the diagnostic
            # one). Move (rename) not copy so the original is gone — that
            # prevents next-restart from re-triggering the same branch.
            base_backup = path.with_suffix(path.suffix + ".bak")
            if base_backup.exists():
                backup_path: Optional[Path] = path.with_suffix(
                    path.suffix + f".bak.{int(time.time())}"
                )
            else:
                backup_path = base_backup
            try:
                # Path.rename atomically replaces / removes the source. Falls
                # back to copy+unlink if rename across filesystems fails.
                try:
                    path.rename(backup_path)
                except OSError:
                    shutil.copy2(path, backup_path)
                    try:
                        path.unlink()
                    except OSError:
                        pass
            except OSError:
                # If even the backup fails (e.g. path vanished), still fall
                # back rather than crash — the user needs a working tool.
                backup_path = None
            logger.error(
                f"Config file at {path} is corrupt: {e}.\n"
                f"Backup saved to {backup_path}.\n"
                f"Falling back to default config. Edit {path} or delete it to reset."
            )
            return get_default_config()

        # Get defaults for variable substitution
        defaults = data.get("defaults", {})

        # BE-A-015: track unresolved ${VAR} references so doctor() can flag
        # them. Substitution silently leaving ${FOO} in args is a debugging
        # trap — the backend then receives the literal string and fails
        # opaquely.
        unresolved: List[str] = []

        def resolve_var(match):
            var_name = match.group(1)
            env_val = os.environ.get(var_name)
            if env_val is not None:
                return env_val
            default_val = defaults.get(var_name)
            if default_val is not None:
                return default_val
            if var_name not in unresolved:
                unresolved.append(var_name)
            return match.group(0)

        # Recursively substitute ${VAR} patterns
        def substitute(obj):
            if isinstance(obj, str):
                return re.sub(r"\$\{(\w+)\}", resolve_var, obj)
            elif isinstance(obj, dict):
                return {k: substitute(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [substitute(item) for item in obj]
            return obj

        data = substitute(data)
        cfg = cls.from_dict(data)
        # Stash unresolved names on the instance (non-serialized) for doctor().
        # The field isn't a declared dataclass attribute, so we attach it
        # directly — dataclasses without slots permit dynamic attributes.
        try:
            cfg._unresolved_vars = list(unresolved)
        except Exception:
            pass
        if unresolved:
            logger.warning(
                f"Config at {path} references unresolved variables: "
                f"{', '.join(unresolved)}. Set them in env or defaults block."
            )
        return cfg

    @classmethod
    def from_dict(cls, data: dict) -> "CompassConfig":
        """Create config from dictionary."""
        config = cls()

        # Parse backends
        for name, backend_data in data.get("backends", {}).items():
            backend_type = backend_data.get("type", "stdio")
            if backend_type == "stdio":
                config.backends[name] = StdioBackend(
                    command=backend_data.get("command", ""),
                    args=backend_data.get("args", []),
                    env=backend_data.get("env", {}),
                    cwd=backend_data.get("cwd"),
                )
            elif backend_type == "http":
                config.backends[name] = HttpBackend(
                    url=backend_data.get("url", ""),
                    headers=backend_data.get("headers", {}),
                    timeout=backend_data.get("timeout", 30.0),
                )
            elif backend_type == "import":
                config.backends[name] = ImportBackend(
                    module=backend_data.get("module", ""),
                    server_var=backend_data.get("server_var", "mcp"),
                )

        # Other settings
        config.embedding_model = data.get("embedding_model", config.embedding_model)
        config.ollama_url = data.get("ollama_url", config.ollama_url)
        config.index_dir = data.get("index_dir", config.index_dir)
        config.auto_sync = data.get("auto_sync", config.auto_sync)
        config.default_top_k = data.get("default_top_k", config.default_top_k)
        config.min_confidence = data.get("min_confidence", config.min_confidence)
        config.progressive_disclosure = data.get(
            "progressive_disclosure", config.progressive_disclosure
        )

        # Sync settings
        config.sync_check_on_startup = data.get(
            "sync_check_on_startup", config.sync_check_on_startup
        )
        config.sync_polling_interval = data.get(
            "sync_polling_interval", config.sync_polling_interval
        )

        # Analytics settings
        config.analytics_enabled = data.get(
            "analytics_enabled", config.analytics_enabled
        )
        config.hot_cache_size = data.get("hot_cache_size", config.hot_cache_size)

        # Chain settings
        config.chain_indexing_enabled = data.get(
            "chain_indexing_enabled", config.chain_indexing_enabled
        )
        config.chain_detection_min_occurrences = data.get(
            "chain_detection_min_occurrences", config.chain_detection_min_occurrences
        )
        config.top_chains_cache_size = data.get(
            "top_chains_cache_size", config.top_chains_cache_size
        )

        # Circuit breaker / retry tuning (BE-B-014)
        config.ollama_breaker_failure_threshold = data.get(
            "ollama_breaker_failure_threshold",
            config.ollama_breaker_failure_threshold,
        )
        config.ollama_breaker_open_seconds = data.get(
            "ollama_breaker_open_seconds", config.ollama_breaker_open_seconds
        )
        config.ollama_retry_attempts = data.get(
            "ollama_retry_attempts", config.ollama_retry_attempts
        )
        backoffs = data.get("ollama_retry_backoffs")
        if backoffs is not None:
            try:
                config.ollama_retry_backoffs = [float(b) for b in backoffs]
            except (TypeError, ValueError):
                logger.warning(
                    "ollama_retry_backoffs must be a list of numbers; ignoring."
                )

        # HNSW tuning (BE-B-008)
        config.hnsw_m = data.get("hnsw_m", config.hnsw_m)
        config.hnsw_ef_construction = data.get(
            "hnsw_ef_construction", config.hnsw_ef_construction
        )
        config.hnsw_ef_search = data.get("hnsw_ef_search", config.hnsw_ef_search)

        # MCC-B-002: clamp out-of-range values rather than letting them slip
        # through and silently produce weird search/cache behavior downstream.
        config.validate_and_clamp()

        return config

    def validate_and_clamp(self) -> None:
        """Clamp config fields to safe ranges, logging each clamp.

        Silent acceptance of out-of-range values was causing debugging pain
        (e.g. negative polling intervals, hot_cache_size=0). Clamp here so
        the surface is always sane even with a hand-edited config file.

        CFG-A-002: COERCE numeric fields BEFORE the range comparisons. A
        hand-edited config can carry a string/null where a number is expected
        (e.g. ``"min_confidence": "high"``); comparing before coercing raised
        TypeError, and from_file's recovery except only catches JSON/OS errors,
        so startup crashed with a raw traceback. We coerce-or-reset each
        numeric field up front: if the value can't become the right numeric
        type, reset it to the class default and warn.
        """
        # CFG-A-002: coerce-or-reset every numeric field first, so the range
        # checks below always operate on numbers. (field, caster, default)
        _defaults = CompassConfig
        for fname, caster in (
            ("min_confidence", float),
            ("default_top_k", int),
            ("sync_polling_interval", int),
            ("hot_cache_size", int),
            ("chain_detection_min_occurrences", int),
            ("ollama_breaker_failure_threshold", int),
            ("ollama_breaker_open_seconds", float),
            ("ollama_retry_attempts", int),
            ("hnsw_m", int),
            ("hnsw_ef_construction", int),
            ("hnsw_ef_search", int),
        ):
            value = getattr(self, fname)
            try:
                # bool is an int subclass; treat it as the numeric it casts to.
                setattr(self, fname, caster(value))
            except (TypeError, ValueError):
                default_value = getattr(_defaults, fname)
                logger.warning(
                    f"Config value {fname}={value!r} is not numeric; "
                    f"resetting to default {default_value!r}"
                )
                setattr(self, fname, default_value)

        # min_confidence: [0.0, 1.0]
        if not 0.0 <= self.min_confidence <= 1.0:
            original = self.min_confidence
            clamped = max(0.0, min(1.0, float(self.min_confidence)))
            logger.warning(
                f"Config value min_confidence clamped from {original} to {clamped}"
            )
            self.min_confidence = clamped

        # default_top_k: [1, 50]
        if not 1 <= self.default_top_k <= 50:
            original = self.default_top_k
            clamped = max(1, min(50, int(self.default_top_k)))
            logger.warning(
                f"Config value default_top_k clamped from {original} to {clamped}"
            )
            self.default_top_k = clamped

        # sync_polling_interval: max(0, value). 0 disables polling by design.
        if self.sync_polling_interval < 0:
            original = self.sync_polling_interval
            clamped = max(0, int(self.sync_polling_interval))
            logger.warning(
                f"Config value sync_polling_interval clamped from {original} to {clamped}"
            )
            self.sync_polling_interval = clamped

        # hot_cache_size: max(1, value). Zero would disable the cache silently.
        if self.hot_cache_size < 1:
            original = self.hot_cache_size
            clamped = max(1, int(self.hot_cache_size))
            logger.warning(
                f"Config value hot_cache_size clamped from {original} to {clamped}"
            )
            self.hot_cache_size = clamped

        # chain_detection_min_occurrences: max(2, value). Below 2, every pair
        # of tools becomes a "chain" and the detector drowns in noise.
        if self.chain_detection_min_occurrences < 2:
            original = self.chain_detection_min_occurrences
            clamped = max(2, int(self.chain_detection_min_occurrences))
            logger.warning(
                f"Config value chain_detection_min_occurrences clamped from {original} to {clamped}"
            )
            self.chain_detection_min_occurrences = clamped

        # BE-B-014: clamp circuit-breaker tuning to safe ranges.
        if not 1 <= self.ollama_breaker_failure_threshold <= 20:
            original = self.ollama_breaker_failure_threshold
            clamped = max(1, min(20, int(self.ollama_breaker_failure_threshold)))
            logger.warning(
                f"Config value ollama_breaker_failure_threshold clamped from "
                f"{original} to {clamped}"
            )
            self.ollama_breaker_failure_threshold = clamped

        if not 1.0 <= self.ollama_breaker_open_seconds <= 600.0:
            original = self.ollama_breaker_open_seconds
            clamped = max(1.0, min(600.0, float(self.ollama_breaker_open_seconds)))
            logger.warning(
                f"Config value ollama_breaker_open_seconds clamped from "
                f"{original} to {clamped}"
            )
            self.ollama_breaker_open_seconds = clamped

        if not 0 <= self.ollama_retry_attempts <= 10:
            original = self.ollama_retry_attempts
            clamped = max(0, min(10, int(self.ollama_retry_attempts)))
            logger.warning(
                f"Config value ollama_retry_attempts clamped from "
                f"{original} to {clamped}"
            )
            self.ollama_retry_attempts = clamped

        if not isinstance(self.ollama_retry_backoffs, list) or not all(
            isinstance(b, (int, float)) and b >= 0 for b in self.ollama_retry_backoffs
        ):
            logger.warning(
                "ollama_retry_backoffs must be a list of non-negative numbers; "
                "resetting to [0.5, 1.0, 2.0]"
            )
            self.ollama_retry_backoffs = [0.5, 1.0, 2.0]

        # BE-B-008: clamp HNSW knobs to safe ranges.
        if not 4 <= self.hnsw_m <= 64:
            original = self.hnsw_m
            self.hnsw_m = max(4, min(64, int(self.hnsw_m)))
            logger.warning(
                f"Config value hnsw_m clamped from {original} to {self.hnsw_m}"
            )
        if not 40 <= self.hnsw_ef_construction <= 800:
            original = self.hnsw_ef_construction
            self.hnsw_ef_construction = max(
                40, min(800, int(self.hnsw_ef_construction))
            )
            logger.warning(
                f"Config value hnsw_ef_construction clamped from "
                f"{original} to {self.hnsw_ef_construction}"
            )
        if not 10 <= self.hnsw_ef_search <= 400:
            original = self.hnsw_ef_search
            self.hnsw_ef_search = max(10, min(400, int(self.hnsw_ef_search)))
            logger.warning(
                f"Config value hnsw_ef_search clamped from "
                f"{original} to {self.hnsw_ef_search}"
            )

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        backends = {}
        for name, backend in self.backends.items():
            if isinstance(backend, StdioBackend):
                backends[name] = {
                    "type": "stdio",
                    "command": backend.command,
                    "args": backend.args,
                    "env": backend.env,
                    "cwd": backend.cwd,
                }
            elif isinstance(backend, HttpBackend):
                backends[name] = {
                    "type": "http",
                    "url": backend.url,
                    "headers": backend.headers,
                    "timeout": backend.timeout,
                }
            elif isinstance(backend, ImportBackend):
                backends[name] = {
                    "type": "import",
                    "module": backend.module,
                    "server_var": backend.server_var,
                }

        return {
            "backends": backends,
            "embedding_model": self.embedding_model,
            "ollama_url": self.ollama_url,
            "index_dir": self.index_dir,
            "auto_sync": self.auto_sync,
            "default_top_k": self.default_top_k,
            "min_confidence": self.min_confidence,
            "progressive_disclosure": self.progressive_disclosure,
            "sync_check_on_startup": self.sync_check_on_startup,
            "sync_polling_interval": self.sync_polling_interval,
            "analytics_enabled": self.analytics_enabled,
            "hot_cache_size": self.hot_cache_size,
            "chain_indexing_enabled": self.chain_indexing_enabled,
            "chain_detection_min_occurrences": self.chain_detection_min_occurrences,
            "top_chains_cache_size": self.top_chains_cache_size,
            "ollama_breaker_failure_threshold": self.ollama_breaker_failure_threshold,
            "ollama_breaker_open_seconds": self.ollama_breaker_open_seconds,
            "ollama_retry_attempts": self.ollama_retry_attempts,
            "ollama_retry_backoffs": list(self.ollama_retry_backoffs),
            "hnsw_m": self.hnsw_m,
            "hnsw_ef_construction": self.hnsw_ef_construction,
            "hnsw_ef_search": self.hnsw_ef_search,
        }

    def save(self, path: Path):
        """Save config to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


def get_base_path() -> Path:
    """
    Get the base path for the project.

    Resolution order:
    1. TOOL_COMPASS_BASE_PATH environment variable
    2. Parent of tool_compass directory (typical install)
    """
    env_path = os.environ.get("TOOL_COMPASS_BASE_PATH")
    if env_path:
        return Path(env_path).resolve()

    # Default: parent of tool_compass directory
    return Path(__file__).parent.parent.resolve()


def get_python_executable() -> str:
    """
    Get the Python executable path.

    Resolution order:
    1. TOOL_COMPASS_PYTHON environment variable
    2. Current Python interpreter (sys.executable)
    3. Platform-specific venv detection
    """
    env_python = os.environ.get("TOOL_COMPASS_PYTHON")
    if env_python:
        return env_python

    # Use current interpreter if running from venv
    if sys.prefix != sys.base_prefix:
        return sys.executable

    # Try to find venv in base path
    base_path = get_base_path()

    # Platform-specific venv paths
    if sys.platform == "win32":
        venv_python = base_path / "venv" / "Scripts" / "python.exe"
    else:
        venv_python = base_path / "venv" / "bin" / "python"

    if venv_python.exists():
        return str(venv_python)

    # Fallback to current interpreter
    return sys.executable


def get_default_config() -> CompassConfig:
    """
    Get default config with no backends configured.

    Users should create a compass_config.json with their own backend configurations.
    See get_example_config() for an example configuration.

    Uses environment variables for Ollama URL and other settings.
    """
    return CompassConfig(
        backends={},  # No backends by default - user must configure
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        auto_sync=True,
        progressive_disclosure=True,
    )


def get_example_config() -> CompassConfig:
    """
    Get example config demonstrating backend configuration patterns.

    This is for documentation purposes - actual paths will vary by installation.
    Copy compass_config.example.json to compass_config.json and customize.

    Uses environment variables and auto-detection for cross-platform support.
    Set TOOL_COMPASS_BASE_PATH to override the project root.
    """
    base_path = get_base_path()
    python_exe = get_python_executable()

    # Default environment for all backends
    base_env = {
        "PYTHONPATH": str(base_path),
        "PYTHONIOENCODING": "utf-8",
    }

    return CompassConfig(
        backends={
            "bridge": StdioBackend(
                command=python_exe,
                args=["-u", str(base_path / "app/mcp/bridge_mcp_server.py")],
                env=base_env.copy(),
            ),
            "comfy": StdioBackend(
                command=python_exe,
                args=["-u", str(base_path / "app/mcp/comfy_mcp_server.py")],
                env={
                    **base_env,
                    "COMFYUI_URL": os.environ.get(
                        "COMFYUI_URL", "http://localhost:8188"
                    ),
                },
            ),
            "video": StdioBackend(
                command=python_exe,
                args=["-u", str(base_path / "app/mcp/video_mcp_server.py")],
                env=base_env.copy(),
            ),
            "chat": StdioBackend(
                command=python_exe,
                args=["-u", str(base_path / "app/mcp/chat_mcp_server.py")],
                env=base_env.copy(),
            ),
            "doc": StdioBackend(
                command=python_exe,
                args=["-u", str(base_path / "app/mcp/doc_mcp_server.py")],
                env=base_env.copy(),
            ),
        },
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        auto_sync=True,
        progressive_disclosure=True,
    )


def get_user_config_dir() -> Path:
    """
    Get the user-writable config directory for Tool Compass.

    Resolution order:
    1. TOOL_COMPASS_DATA_DIR environment variable
    2. Platform-specific user config directory:
       - Windows: %LOCALAPPDATA%/tool-compass
       - macOS: ~/Library/Application Support/tool-compass
       - Linux: ~/.config/tool-compass (or $XDG_CONFIG_HOME/tool-compass)
    3. Fallback: .tool-compass in current working directory (if HOME unavailable)
    """
    env_dir = os.environ.get("TOOL_COMPASS_DATA_DIR")
    if env_dir:
        return Path(env_dir).resolve()

    def _safe_home() -> Path:
        """Get home directory with fallback for CI environments."""
        try:
            return Path.home()
        except (RuntimeError, KeyError):
            # HOME/USERPROFILE not set (common in CI)
            return Path.cwd()

    if sys.platform == "win32":
        # Windows: use LOCALAPPDATA
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "tool-compass"
        return _safe_home() / "AppData" / "Local" / "tool-compass"
    elif sys.platform == "darwin":
        # macOS: use Application Support
        return _safe_home() / "Library" / "Application Support" / "tool-compass"
    else:
        # Linux/Unix: use XDG_CONFIG_HOME or ~/.config
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            return Path(xdg_config) / "tool-compass"
        return _safe_home() / ".config" / "tool-compass"


def get_config_path() -> Path:
    """
    Get the config file path.

    Resolution order:
    1. TOOL_COMPASS_CONFIG environment variable
    2. User config directory: <user_config_dir>/compass_config.json
    """
    env_config = os.environ.get("TOOL_COMPASS_CONFIG")
    if env_config:
        return Path(env_config).resolve()
    return get_user_config_dir() / "compass_config.json"


# Default config file location (for backward compatibility)
CONFIG_PATH = get_config_path()


def load_config() -> CompassConfig:
    """Load config from file or return defaults."""
    config_path = get_config_path()
    if config_path.exists():
        return CompassConfig.from_file(config_path)
    return get_default_config()


# Field-name substrings that indicate a secret — redacted in doctor() dumps.
# No such fields exist today, but the scan is defensive in case someone adds
# a "github_token" or "api_key" field and forgets to redact it.
_SECRET_FIELD_HINTS = ("_token", "_key", "_secret", "_password")


# CFG-A-001: backend sub-fields that carry ${VAR}-resolved secrets. Their KEY
# names ('Authorization', 'GITHUB_TOKEN', '--password=...') don't all match
# _SECRET_FIELD_HINTS, so name-based redaction misses them. Redact these
# STRUCTURALLY — every value (dict) or entry (list) — while keeping the keys
# visible so the doctor() dump stays diagnosable.
_SECRET_STRUCT_FIELDS = ("env", "headers", "args")


def _redact_structural(value):
    """Redact a backend env/headers (dict values) or args (list entries),
    preserving keys/structure so the dump shows e.g. 'Authorization:
    [REDACTED]' rather than dropping the field entirely."""
    if isinstance(value, dict):
        return {k: "[REDACTED]" for k in value}
    if isinstance(value, list):
        return ["[REDACTED]" for _ in value]
    return "[REDACTED]"


def redact_url_credentials(value):
    """CFG-A-001 (post-fix sibling): strip userinfo from an http(s) URL so a
    credentialed endpoint like ``http://user:${TOKEN}@host:11434`` (ollama_url
    or a backend ``url``, both ${VAR}-substituted at load) doesn't leak its
    secret into the doctor()/show_config diagnostic dumps. Host:port is kept
    for diagnosability. Non-URL / credential-free values pass through."""
    if not isinstance(value, str) or "://" not in value:
        return value
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not (parts.username or parts.password):
        return value
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit(
        (parts.scheme, f"[REDACTED]@{host}", parts.path, parts.query, parts.fragment)
    )


def _redact_config(cfg_dict: dict) -> dict:
    """Walk the config dict and redact secrets.

    Two layers:
    1. Name-based — any field whose key hints at a secret (_SECRET_FIELD_HINTS).
    2. Structural (CFG-A-001) — under each backend, the 'env'/'headers'/'args'
       fields carry ${VAR}-resolved secrets whose keys don't match the name
       hints, so their values/entries are redacted structurally with keys kept.
    """

    def walk(obj):
        if isinstance(obj, dict):
            redacted = {}
            for k, v in obj.items():
                if isinstance(k, str) and any(
                    hint in k.lower() for hint in _SECRET_FIELD_HINTS
                ):
                    redacted[k] = "[REDACTED]"
                elif isinstance(k, str) and k in _SECRET_STRUCT_FIELDS:
                    redacted[k] = _redact_structural(v)
                else:
                    redacted[k] = walk(v)
            return redacted
        if isinstance(obj, list):
            return [walk(item) for item in obj]
        # Leaf scalar: scrub embedded URL credentials (ollama_url, backend url).
        return redact_url_credentials(obj)

    return walk(cfg_dict)


def _ollama_reachable(url: str, timeout: float = 2.0) -> bool:
    """Quick reachability probe for the doctor dump. Never blocks > timeout."""
    try:
        import httpx  # local import — keeps module-level imports stable
    except ImportError:
        return False
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(f"{url.rstrip('/')}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


def doctor() -> dict:
    """Produce a JSON-serializable diagnostic dump.

    MCC-B-004: one-shot environment snapshot for bug reports. Captures
    version, platform, resolved paths, file sizes, and an Ollama reachability
    probe. Secrets are redacted defensively on field-name match. Ollama probe
    has a hard 2s timeout so `python config.py` never hangs on a dead server.
    """
    # Local imports to avoid polluting the module namespace with rarely-used
    # stdlib paths and to keep import-time cost low on the hot path.
    from _version import __version__

    # MCC-FT-002 bonus: include deprecated tool count in the diagnostic dump
    # so bug reports surface stale tools without a separate introspection
    # step. Defensive — tool_manifest should always import, but if it breaks
    # we still want doctor() to succeed for the user.
    deprecated_tools_count: Optional[int] = None
    try:
        from tool_manifest import get_all_tools

        deprecated_tools_count = sum(
            1 for t in get_all_tools() if t.deprecated_since is not None
        )
    except Exception as e:
        logger.debug(f"doctor(): could not count deprecated tools: {e}")

    cfg_path = get_config_path()
    cfg = load_config()
    cfg_dict = _redact_config(cfg.to_dict())

    base_path = get_base_path()
    data_dir = get_user_config_dir()
    python_exe = get_python_executable()

    index_path = Path(cfg.index_dir)
    if not index_path.is_absolute():
        index_path = (base_path / cfg.index_dir).resolve()
    index_exists = index_path.exists()
    index_size = (
        sum(p.stat().st_size for p in index_path.rglob("*") if p.is_file())
        if index_exists and index_path.is_dir()
        else (index_path.stat().st_size if index_exists else 0)
    )

    # Analytics DB lives at <module_dir>/db/compass_analytics.db — matches
    # analytics.ANALYTICS_DB_PATH. Resolve here without importing analytics
    # to avoid dragging in sqlite3 at doctor-run time.
    analytics_db_path = Path(__file__).parent / "db" / "compass_analytics.db"
    analytics_exists = analytics_db_path.exists()
    analytics_size = analytics_db_path.stat().st_size if analytics_exists else 0
    analytics_schema_version: Optional[int] = None
    if analytics_exists:
        try:
            import sqlite3

            with sqlite3.connect(str(analytics_db_path)) as _db:
                row = _db.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row:
                    analytics_schema_version = int(row[0])
        except Exception:
            # Old DB without schema_meta is fine — just report unknown.
            analytics_schema_version = None

    unresolved_vars = list(getattr(cfg, "_unresolved_vars", []) or [])

    return {
        "version": __version__,
        "python_version": sys.version,
        "platform": _platform.platform(),
        "config_path": str(cfg_path),
        "config": cfg_dict,
        # BE-A-015: surface unresolved ${VAR} references so bug reports
        # capture them. Empty list means the config substituted cleanly.
        "config_unresolved_vars": unresolved_vars,
        "base_path": str(base_path),
        "data_dir": str(data_dir),
        "python_executable": python_exe,
        "index_path": str(index_path),
        "index_exists": index_exists,
        "index_size_bytes": index_size,
        "analytics_db_path": str(analytics_db_path),
        "analytics_exists": analytics_exists,
        "analytics_size_bytes": analytics_size,
        "analytics_schema_version": analytics_schema_version,
        # CFG-A-001 sibling: scrub any user:pass@ embedded in the URL before
        # it lands in a pasteable bug-report dump. The reachability probe below
        # still uses the raw cfg value (it returns only a bool, not the URL).
        "ollama_url": redact_url_credentials(cfg.ollama_url),
        "ollama_reachable": _ollama_reachable(cfg.ollama_url),
        "deprecated_tools": deprecated_tools_count,
    }


if __name__ == "__main__":
    # Human-runnable diagnostic dump — `python config.py` for bug reports.
    print(json.dumps(doctor(), indent=2, default=str))
