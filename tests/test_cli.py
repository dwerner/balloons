"""Tests for CLI arguments."""

import os
import subprocess
import sys
from pathlib import Path


def run_main_with_config(config_path: str | None, *args: str) -> subprocess.CompletedProcess:
    """Run main.py with a specific config file."""
    env = os.environ.copy()
    if config_path:
        env["BALLOONS_CONFIG"] = config_path
    return subprocess.run(
        [sys.executable, "main.py", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).parent.parent,
    )


class TestListBackends:
    """Tests for --list-backends flag."""

    def test_list_backends_exits_zero(self, tmp_path):
        """--list-backends exits with code 0."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
default_backend: claude

backends:
  claude: {}
  llama70b:
    base_url: "http://localhost:4000"
    api_key: "test-key"
""")

        result = run_main_with_config(str(config_file), "--list-backends")

        assert result.returncode == 0

    def test_list_backends_shows_default(self, tmp_path):
        """--list-backends marks the default backend."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
default_backend: llama70b

backends:
  claude: {}
  llama70b:
    base_url: "http://localhost:4000"
""")

        result = run_main_with_config(str(config_file), "--list-backends")

        assert "default: llama70b" in result.stdout
        assert "llama70b *" in result.stdout

    def test_list_backends_shows_urls(self, tmp_path):
        """--list-backends shows backend URLs."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
default_backend: claude

backends:
  claude: {}
  llama70b:
    base_url: "http://192.168.0.120:4000"
""")

        result = run_main_with_config(str(config_file), "--list-backends")

        assert "http://192.168.0.120:4000" in result.stdout
        assert "native Claude API" in result.stdout

    def test_list_backends_no_config(self, tmp_path):
        """--list-backends works with no config file (defaults to claude)."""
        result = run_main_with_config(str(tmp_path / "nonexistent.yaml"), "--list-backends")

        assert result.returncode == 0
        assert "claude" in result.stdout
        assert "default: claude" in result.stdout
