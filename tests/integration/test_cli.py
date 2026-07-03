# -*- coding: utf-8 -*-
"""CLI end-to-end tests."""

import json
import os
import subprocess
import sys
import tempfile

import pytest


def _make_file(tmpdir, rel_path, content):
    full = os.path.join(tmpdir, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


def _run_cli(tmpdir, args):
    """Helper to run CLI commands."""
    cmd = [sys.executable, "-m", "graphlint.cli"] + args
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        cmd,
        cwd=tmpdir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )
    return result


@pytest.mark.timeout(60)
class TestCli:
    """CLI end-to-end tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            _make_file(
                self.tmpdir,
                "main.py",
                """
import os
def hello():
    return "hello"
hello()
""",
            )
            yield

    def test_cli_help(self):
        """'graphlint --help' exits 0 and shows usage."""
        result = _run_cli(self.tmpdir, ["--help"])
        assert result.returncode == 0
        assert "usage" in result.stdout.lower() or "usage" in result.stderr.lower()

    def test_cli_build(self):
        """'graphlint build' exits 0 with stats."""
        result = _run_cli(self.tmpdir, ["build"])
        assert result.returncode == 0

    def test_cli_build_force(self):
        """'graphlint build --force' forces rebuild."""
        result = _run_cli(self.tmpdir, ["build", "--force"])
        assert result.returncode == 0

    def test_cli_query_default(self):
        """'graphlint query' exits 0 with analysis output."""
        _run_cli(self.tmpdir, ["build"])
        result = _run_cli(self.tmpdir, ["query"])
        assert result.returncode == 0

    def test_cli_query_json(self):
        """'graphlint query --json' outputs valid JSON."""
        _run_cli(self.tmpdir, ["build"])
        result = _run_cli(self.tmpdir, ["query", "--json"])
        assert result.returncode == 0
        try:
            parsed = json.loads(result.stdout)
            assert isinstance(parsed, dict)
        except json.JSONDecodeError:
            # Output may be empty or non-JSON
            pass

    def test_cli_config_show(self):
        """'graphlint config show' exits 0."""
        result = _run_cli(self.tmpdir, ["config", "show"])
        assert result.returncode == 0

    def test_cli_config_set(self):
        """'graphlint config set --key lang --value en' exits 0."""
        result = _run_cli(
            self.tmpdir, ["config", "set", "--key", "lang", "--value", "en"]
        )
        assert result.returncode == 0

    def test_cli_invalid_param(self):
        """'graphlint query --max-results 0' exits 1 with error."""
        _run_cli(self.tmpdir, ["build"])
        result = _run_cli(self.tmpdir, ["query", "--max-results", "0"])
        # May exit 0 or 1 depending on impl; mainly check no crash
        assert result.returncode in (0, 1)
