"""
Tests for Tool Compass configuration module.

Tests cross-platform path handling and environment variable support.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from config import (
    CompassConfig,
    StdioBackend,
    HttpBackend,
    ImportBackend,
    get_base_path,
    get_python_executable,
    get_config_path,
    get_default_config,
    load_config,
    doctor,
    _redact_config,
)


class TestPathResolution:
    """Test cross-platform path resolution."""

    def test_get_base_path_default(self):
        """Default base path should be parent of tool_compass directory."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove env var if set
            os.environ.pop("TOOL_COMPASS_BASE_PATH", None)
            base = get_base_path()
            assert base.exists()
            assert base.is_dir()

    def test_get_base_path_from_env(self, tmp_path):
        """TOOL_COMPASS_BASE_PATH should override default."""
        with patch.dict(os.environ, {"TOOL_COMPASS_BASE_PATH": str(tmp_path)}):
            base = get_base_path()
            assert base == tmp_path.resolve()

    def test_get_python_executable_from_env(self):
        """TOOL_COMPASS_PYTHON should override detection."""
        fake_python = "/usr/bin/fake_python"
        with patch.dict(os.environ, {"TOOL_COMPASS_PYTHON": fake_python}):
            exe = get_python_executable()
            assert exe == fake_python

    def test_get_python_executable_default(self):
        """Default should use sys.executable or venv detection."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TOOL_COMPASS_PYTHON", None)
            exe = get_python_executable()
            assert exe  # Should return something
            # Should be a valid path or the current interpreter
            assert Path(exe).exists() or exe == sys.executable

    def test_get_python_executable_env_nonexistent_falls_back(self, tmp_path):
        """If TOOL_COMPASS_PYTHON points to a nonexistent path, behavior must
        be well-defined — exercise the OR branch in get_python_executable so
        that path isn't silently untested. Historically this branch referenced
        an unimported `sys`, so the fallback raised NameError instead of
        returning a valid interpreter.
        """
        fake = str(tmp_path / "does_not_exist_python")
        assert not Path(fake).exists()
        # Current contract: env var wins verbatim (caller owns validation).
        # This test LOCKS IN that contract and executes the code path without
        # raising NameError — if the implementation later changes to validate
        # existence and fall back, adjust this assertion accordingly.
        with patch.dict(os.environ, {"TOOL_COMPASS_PYTHON": fake}):
            exe = get_python_executable()
            # Must not raise NameError; must return a non-empty string.
            assert isinstance(exe, str)
            assert exe  # non-empty
            # Either verbatim env value, or a real existing interpreter
            # (sys.executable fallback).
            assert exe == fake or Path(exe).exists() or exe == sys.executable

    def test_get_config_path_from_env(self, tmp_path):
        """TOOL_COMPASS_CONFIG should override default."""
        config_file = tmp_path / "custom_config.json"
        with patch.dict(os.environ, {"TOOL_COMPASS_CONFIG": str(config_file)}):
            path = get_config_path()
            assert path == config_file.resolve()

    def test_get_config_path_default(self):
        """Default config path should be in tool_compass/tool-compass directory."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TOOL_COMPASS_CONFIG", None)
            path = get_config_path()
            assert path.name == "compass_config.json"
            # Accept both tool_compass (local) and tool-compass (CI/GitHub)
            path_str = str(path).lower()
            assert "tool_compass" in path_str or "tool-compass" in path_str


class TestCompassConfig:
    """Test CompassConfig dataclass and parsing."""

    def test_default_values(self):
        """Config should have sensible defaults."""
        config = CompassConfig()
        assert config.embedding_model == "nomic-embed-text"
        assert config.ollama_url == "http://localhost:11434"
        assert config.default_top_k == 5
        assert config.min_confidence == 0.3
        assert config.progressive_disclosure is True

    def test_from_dict_minimal(self):
        """Should parse minimal config dict."""
        data = {"backends": {}}
        config = CompassConfig.from_dict(data)
        assert config.backends == {}
        assert config.auto_sync is True  # default

    def test_from_dict_with_stdio_backend(self):
        """Should parse stdio backend config."""
        data = {
            "backends": {
                "test": {
                    "type": "stdio",
                    "command": "python",
                    "args": ["-m", "test_server"],
                    "env": {"DEBUG": "1"},
                }
            }
        }
        config = CompassConfig.from_dict(data)
        assert "test" in config.backends
        backend = config.backends["test"]
        assert isinstance(backend, StdioBackend)
        assert backend.command == "python"
        assert backend.args == ["-m", "test_server"]
        assert backend.env == {"DEBUG": "1"}

    def test_from_dict_with_http_backend(self):
        """Should parse HTTP backend config."""
        data = {
            "backends": {
                "api": {
                    "type": "http",
                    "url": "http://localhost:8080/mcp",
                    "headers": {"Authorization": "Bearer token"},
                    "timeout": 60.0,
                }
            }
        }
        config = CompassConfig.from_dict(data)
        backend = config.backends["api"]
        assert isinstance(backend, HttpBackend)
        assert backend.url == "http://localhost:8080/mcp"
        assert backend.timeout == 60.0

    def test_from_dict_with_import_backend(self):
        """Should parse import backend config."""
        data = {
            "backends": {
                "local": {
                    "type": "import",
                    "module": "my_server",
                    "server_var": "app",
                }
            }
        }
        config = CompassConfig.from_dict(data)
        backend = config.backends["local"]
        assert isinstance(backend, ImportBackend)
        assert backend.module == "my_server"
        assert backend.server_var == "app"

    def test_to_dict_roundtrip(self):
        """Config should survive dict roundtrip."""
        original = CompassConfig(
            backends={
                "test": StdioBackend(
                    command="python",
                    args=["-m", "server"],
                    env={"KEY": "value"},
                )
            },
            embedding_model="custom-model",
            auto_sync=False,
        )
        data = original.to_dict()
        restored = CompassConfig.from_dict(data)

        assert restored.embedding_model == original.embedding_model
        assert restored.auto_sync == original.auto_sync
        assert "test" in restored.backends


class TestDefaultConfig:
    """Test default configuration generation."""

    def test_get_default_config_structure(self):
        """Default config should have empty backends (user must configure)."""
        config = get_default_config()

        # Default config ships with no backends - user must configure
        assert config.backends == {}
        assert config.embedding_model == "nomic-embed-text"
        assert config.auto_sync is True
        assert config.progressive_disclosure is True

    def test_get_default_config_uses_detected_python(self):
        """Default config has no backends; example config uses detected Python."""
        config = get_default_config()
        # Default config has no backends to check
        assert config.backends == {}

    def test_get_default_config_portable_paths(self):
        """Default config has no backends; paths are user-configured."""
        config = get_default_config()
        # Default config has no backends - paths are user responsibility
        assert config.backends == {}


class TestLoadConfig:
    """Test config file loading."""

    def test_load_config_missing_file(self, tmp_path):
        """Should return defaults if config file doesn't exist."""
        with patch.dict(
            os.environ, {"TOOL_COMPASS_CONFIG": str(tmp_path / "missing.json")}
        ):
            config = load_config()
            # Should get default config
            assert config.embedding_model == "nomic-embed-text"

    def test_load_config_from_file(self, tmp_path):
        """Should load config from JSON file."""
        config_file = tmp_path / "test_config.json"
        config_file.write_text("""{
            "backends": {},
            "embedding_model": "custom-model",
            "auto_sync": false
        }""")

        with patch.dict(os.environ, {"TOOL_COMPASS_CONFIG": str(config_file)}):
            config = load_config()
            assert config.embedding_model == "custom-model"
            assert config.auto_sync is False


class TestRedactConfig:
    """CFG-A-001: structural redaction of resolved secrets in doctor() dumps.

    Name-based redaction only catches keys that *look* secret
    (_token/_key/_secret/_password). But the ${VAR} substitution feature
    resolves env secrets INTO backend headers/env/args, where the KEY names
    (e.g. 'Authorization', 'GITHUB_TOKEN') don't all match those hints —
    so resolved secret VALUES used to leak verbatim from doctor()'s dump.
    Redact STRUCTURALLY: for every backend's 'env'/'headers' (dicts) redact
    all VALUES, and for 'args' (list) redact all entries, while KEEPING THE
    KEYS visible so the dump stays diagnosable.
    """

    SECRET_HEADER = "Bearer SEKRET_HEADER_TOKEN_abc123"
    SECRET_ENV = "ghp_SEKRET_ENV_TOKEN_xyz789"
    SECRET_ARG = "--password=SEKRET_ARG_VALUE_qwe456"

    def _secret_values(self):
        return [self.SECRET_HEADER, self.SECRET_ENV, self.SECRET_ARG]

    def _build_config(self):
        return CompassConfig(
            backends={
                "remote": HttpBackend(
                    url="http://localhost:9000/mcp",
                    headers={"Authorization": self.SECRET_HEADER},
                ),
                "local": StdioBackend(
                    command="python",
                    args=["-m", "server", self.SECRET_ARG],
                    env={"GITHUB_TOKEN": self.SECRET_ENV},
                ),
            }
        )

    def test_redact_config_hides_resolved_secret_values(self):
        """Resolved secret VALUES must not appear; KEYS must remain visible."""
        cfg = self._build_config()
        redacted = _redact_config(cfg.to_dict())

        blob = json.dumps(redacted)
        for secret in self._secret_values():
            assert secret not in blob, (
                f"secret value leaked into redacted dump: {secret!r}"
            )

        backends = redacted["backends"]
        # Header value redacted, but the 'Authorization' key still visible.
        assert "Authorization" in backends["remote"]["headers"]
        assert backends["remote"]["headers"]["Authorization"] == "[REDACTED]"
        # Env value redacted, key 'GITHUB_TOKEN' still visible.
        assert "GITHUB_TOKEN" in backends["local"]["env"]
        assert backends["local"]["env"]["GITHUB_TOKEN"] == "[REDACTED]"
        # Args entries redacted (the secret-bearing entry at minimum).
        assert self.SECRET_ARG not in backends["local"]["args"]
        assert all(a == "[REDACTED]" for a in backends["local"]["args"])
        # Non-secret structural fields stay intact for diagnosability.
        assert backends["remote"]["url"] == "http://localhost:9000/mcp"
        assert backends["remote"]["type"] == "http"
        assert backends["local"]["command"] == "python"

    def test_doctor_does_not_leak_resolved_secrets(self, tmp_path):
        """End-to-end: a config file with resolved ${VAR} secrets in a
        header + env must not surface those secret values from doctor()."""
        config_file = tmp_path / "compass_config.json"
        config_file.write_text(json.dumps({
            "backends": {
                "remote": {
                    "type": "http",
                    "url": "http://localhost:9000/mcp",
                    "headers": {"Authorization": "Bearer ${MY_API_TOKEN}"},
                },
                "local": {
                    "type": "stdio",
                    "command": "python",
                    "args": ["-m", "server", "${MY_CLI_ARG}"],
                    "env": {"GITHUB_TOKEN": "${MY_GH_TOKEN}"},
                },
            }
        }))

        env = {
            "TOOL_COMPASS_CONFIG": str(config_file),
            "MY_API_TOKEN": "live_header_secret_111",
            "MY_GH_TOKEN": "ghp_live_env_secret_222",
            "MY_CLI_ARG": "--password=live_arg_secret_333",
        }
        with patch.dict(os.environ, env):
            report = doctor()

        blob = json.dumps(report, default=str)
        for secret in (
            "live_header_secret_111",
            "ghp_live_env_secret_222",
            "live_arg_secret_333",
        ):
            assert secret not in blob, f"doctor() leaked secret {secret!r}"

        # Keys remain visible in the redacted config so the dump is usable.
        backends = report["config"]["backends"]
        assert "Authorization" in backends["remote"]["headers"]
        assert backends["remote"]["headers"]["Authorization"] == "[REDACTED]"
        assert "GITHUB_TOKEN" in backends["local"]["env"]
        assert backends["local"]["env"]["GITHUB_TOKEN"] == "[REDACTED]"


class TestRedactUrlCredentials:
    """CFG-A-001 (sibling): a credentialed ollama_url like
    ``http://user:${TOKEN}@host:11434`` must have its userinfo stripped to
    ``http://[REDACTED]@host:11434`` in doctor() output and in _redact_config,
    while host:port stays visible for diagnosability.

    The ${VAR} substitution feature resolves env secrets INTO ollama_url
    userinfo at load time; without this the raw user:secret@ landed verbatim
    in a pasteable bug-report dump.
    """

    def test_redact_url_credentials_strips_userinfo(self):
        from config import redact_url_credentials

        out = redact_url_credentials("http://u:livesecret@h:11434")
        assert "livesecret" not in out
        assert out == "http://[REDACTED]@h:11434"

    def test_redact_url_credentials_passthrough_when_no_userinfo(self):
        from config import redact_url_credentials

        # No credentials -> unchanged, host:port intact.
        assert (
            redact_url_credentials("http://localhost:11434")
            == "http://localhost:11434"
        )

    def test_redact_config_scrubs_ollama_url_userinfo(self):
        """_redact_config must scrub embedded userinfo from ollama_url (a leaf
        scalar) while keeping the host visible."""
        cfg = CompassConfig(ollama_url="http://u:livesecret@h:11434")
        redacted = _redact_config(cfg.to_dict())
        blob = json.dumps(redacted)
        assert "livesecret" not in blob, "ollama_url secret leaked"
        assert redacted["ollama_url"] == "http://[REDACTED]@h:11434"
        assert "h:11434" in redacted["ollama_url"]

    def test_doctor_redacts_ollama_url_credentials(self, tmp_path):
        """End-to-end: doctor() must not surface the ollama_url userinfo secret
        but must keep host:port for diagnosability."""
        config_file = tmp_path / "compass_config.json"
        config_file.write_text(json.dumps({
            "backends": {},
            "ollama_url": "http://u:${OLLAMA_PW}@h:11434",
        }))
        env = {
            "TOOL_COMPASS_CONFIG": str(config_file),
            "OLLAMA_PW": "livesecret",
        }
        with patch.dict(os.environ, env):
            report = doctor()

        blob = json.dumps(report, default=str)
        assert "livesecret" not in blob, "doctor() leaked ollama_url secret"
        # Host:port survives in both the top-level field and the config dump.
        assert "h:11434" in report["ollama_url"]
        assert report["ollama_url"] == "http://[REDACTED]@h:11434"
        assert "h:11434" in report["config"]["ollama_url"]
        assert "livesecret" not in report["config"]["ollama_url"]


class TestValidateAndClampCoercion:
    """CFG-A-002: validate_and_clamp must survive non-numeric hand-edited
    values. The compare-before-coerce ordering raised TypeError on a string
    or null numeric BEFORE the int()/float() cast, and from_file's recovery
    except only catches (json.JSONDecodeError, OSError) — so a hand-edited
    config crashed startup with a raw traceback, contradicting the docstring's
    'safe even with a hand-edited config file.'"""

    def test_from_dict_bad_numeric_types_do_not_crash(self):
        """A config dict with string/null numeric fields must coerce-or-reset
        to defaults instead of raising TypeError."""
        defaults = CompassConfig()
        data = {
            "backends": {},
            "min_confidence": "high",          # non-numeric string
            "default_top_k": None,             # null
            "sync_polling_interval": "soon",   # non-numeric string
            "hot_cache_size": None,            # null
            "chain_detection_min_occurrences": "lots",
            "ollama_breaker_failure_threshold": None,
            "ollama_breaker_open_seconds": "forever",
            "ollama_retry_attempts": None,
            "hnsw_m": "big",
            "hnsw_ef_construction": None,
            "hnsw_ef_search": "fast",
        }
        # Must NOT raise.
        config = CompassConfig.from_dict(data)

        # Each bad field reset to its in-range default (or a clamped default).
        assert config.min_confidence == defaults.min_confidence
        assert config.default_top_k == defaults.default_top_k
        assert config.sync_polling_interval == defaults.sync_polling_interval
        assert config.hot_cache_size == defaults.hot_cache_size
        assert (
            config.chain_detection_min_occurrences
            == defaults.chain_detection_min_occurrences
        )
        assert (
            config.ollama_breaker_failure_threshold
            == defaults.ollama_breaker_failure_threshold
        )
        assert (
            config.ollama_breaker_open_seconds
            == defaults.ollama_breaker_open_seconds
        )
        assert config.ollama_retry_attempts == defaults.ollama_retry_attempts
        assert config.hnsw_m == defaults.hnsw_m
        assert config.hnsw_ef_construction == defaults.hnsw_ef_construction
        assert config.hnsw_ef_search == defaults.hnsw_ef_search

    def test_from_file_with_hand_edited_bad_values_recovers(self, tmp_path):
        """from_file on a syntactically-valid JSON with bad numeric types
        must load without crashing (the docstring's stated guarantee)."""
        config_file = tmp_path / "compass_config.json"
        config_file.write_text(json.dumps({
            "backends": {},
            "min_confidence": "high",
            "default_top_k": None,
            "embedding_model": "custom-model",
        }))
        with patch.dict(os.environ, {"TOOL_COMPASS_CONFIG": str(config_file)}):
            config = load_config()  # must not raise
        # Non-numeric fields untouched, numeric fields reset to defaults.
        assert config.embedding_model == "custom-model"
        assert config.min_confidence == CompassConfig().min_confidence
        assert config.default_top_k == CompassConfig().default_top_k
