# -*- coding: utf-8 -*-
"""Tests for agent tool installation — skills, legacy prompts, DSH plugin."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

from graphlint import __version__, agent_tools


@pytest.fixture()
def fake_home(monkeypatch):
    """Point ~ at a temp dir for both POSIX and Windows expanduser.

    Uses os.makedirs on a unique path instead of pytest's tmp_path or
    tempfile.mkdtemp: under restricted sandboxes pytest's basetemp enumeration
    fails and mkdtemp-created dirs block later writes, while plain makedirs
    works. Cleanup tolerates sandboxes where rmtree enumeration is denied
    (leftovers stay under .glhome-tests/, which is git-ignored).
    """
    root = os.path.join(os.getcwd(), ".glhome-tests")
    os.makedirs(root, exist_ok=True)
    tmpdir = os.path.join(root, f"glhome-{uuid.uuid4().hex[:8]}")
    os.makedirs(tmpdir)
    monkeypatch.setenv("HOME", tmpdir)
    monkeypatch.setenv("USERPROFILE", tmpdir)
    try:
        yield tmpdir
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _skill_path(home, rel: str = ".agents/skills/graphlint/SKILL.md") -> str:
    return os.path.join(str(home), rel)


def _read_skill(home, rel: str = ".agents/skills/graphlint/SKILL.md") -> str:
    with open(_skill_path(home, rel), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Skill install
# ---------------------------------------------------------------------------


def test_install_skill_creates_file_with_frontmatter_and_version(fake_home) -> None:
    result = agent_tools.install_skills()
    assert "Installed" in result
    content = _read_skill(fake_home)
    assert content.startswith("---\nname: graphlint\n")
    assert f"version: {__version__}" in content
    assert "graphlint query" in content
    # Installed file must equal the canonical document plus the version line.
    canonical = agent_tools.load_skill_markdown()
    end = canonical.find("\n---", 3)
    expected = canonical[:end] + f"\nversion: {__version__}\n" + canonical[end:]
    assert content == expected


def test_install_skill_reports_uptodate_on_second_run(fake_home) -> None:
    agent_tools.install_skills()
    result = agent_tools.install_skills()
    assert "up to date" in result


def test_install_skill_reports_update_on_older_version(fake_home) -> None:
    path = _skill_path(fake_home)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\nname: graphlint\nversion: 0.0.1\ndescription: old\n---\nold body\n")
    result = agent_tools.install_skills()
    assert "Updated" in result
    assert "0.0.1" in result
    assert f"version: {__version__}" in _read_skill(fake_home)


def test_install_targets_all_and_single(fake_home) -> None:
    agent_tools.install_skills("all")
    assert os.path.isfile(_skill_path(fake_home))
    assert os.path.isfile(_skill_path(fake_home, ".claude/skills/graphlint/SKILL.md"))

    # A single target does not touch the other directory.
    claude_path = _skill_path(fake_home, ".claude/skills/graphlint/SKILL.md")
    os.remove(claude_path)
    agent_tools.install_skills("agents")
    assert not os.path.isfile(claude_path)
    assert os.path.isfile(_skill_path(fake_home))


def test_install_unknown_target_errors_without_writing(fake_home) -> None:
    result = agent_tools.install_skills("bogus")
    assert "bogus" in result
    assert not os.path.isfile(_skill_path(fake_home))


# ---------------------------------------------------------------------------
# Skill uninstall
# ---------------------------------------------------------------------------


def test_uninstall_skill_removes_file_and_empty_dir(fake_home) -> None:
    agent_tools.install_skills()
    result = agent_tools.uninstall_skills()
    assert "Removed" in result
    assert not os.path.exists(_skill_path(fake_home))
    assert not os.path.exists(os.path.dirname(_skill_path(fake_home)))


def test_uninstall_skill_reports_not_found(fake_home) -> None:
    result = agent_tools.uninstall_skills()
    assert "No graphlint skill found" in result


def test_uninstall_skill_skips_foreign_file(fake_home) -> None:
    path = _skill_path(fake_home)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# user's own file\n")
    result = agent_tools.uninstall_skills()
    assert "skipped" in result
    assert os.path.isfile(path)


def test_uninstall_skill_keeps_dir_with_extra_files(fake_home) -> None:
    agent_tools.install_skills()
    dir_path = os.path.dirname(_skill_path(fake_home))
    with open(os.path.join(dir_path, "notes.md"), "w", encoding="utf-8") as f:
        f.write("user notes\n")
    agent_tools.uninstall_skills()
    assert not os.path.isfile(_skill_path(fake_home))
    assert os.path.isfile(os.path.join(dir_path, "notes.md"))


# ---------------------------------------------------------------------------
# DSH plugin install
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_dsh(monkeypatch):
    """Fake the dsh executable and subprocess.run."""
    calls = {}

    def fake_which(cmd: str):
        return "C:/dsh/dsh.exe" if cmd == "dsh" else None

    def fake_run(cmd, **kwargs):
        calls["argv"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(agent_tools.shutil, "which", fake_which)
    monkeypatch.setattr(agent_tools.subprocess, "run", fake_run)
    return calls


def test_install_dsh_builds_plugin_add_command(fake_dsh) -> None:
    result = agent_tools.install_dsh(profile="web")
    assert "profile 'web'" in result
    assert fake_dsh["argv"] == [
        "C:/dsh/dsh.exe",
        "plugin",
        "--profile",
        "web",
        "add",
        "dsh-graphlint",
    ]


def test_install_dsh_omits_profile_when_not_given(fake_dsh) -> None:
    agent_tools.install_dsh()
    assert fake_dsh["argv"] == ["C:/dsh/dsh.exe", "plugin", "add", "dsh-graphlint"]


def test_install_dsh_local_links_repo_checkout(fake_dsh, fake_home, monkeypatch) -> None:
    repo = os.path.join(fake_home, "graphlint")
    os.makedirs(os.path.join(repo, "integrations", "dsh"), exist_ok=True)
    with open(os.path.join(repo, "integrations", "dsh", "package.json"), "w", encoding="utf-8") as f:
        f.write("{}\n")
    monkeypatch.chdir(repo)
    result = agent_tools.install_dsh(profile="web", local=True)
    assert "profile 'web'" in result
    assert fake_dsh["argv"][-1] == f"link:{os.path.join(repo, 'integrations', 'dsh')}"


def test_install_dsh_local_accepts_explicit_path(fake_dsh, fake_home) -> None:
    checkout = os.path.join(fake_home, "elsewhere")
    os.makedirs(checkout, exist_ok=True)
    with open(os.path.join(checkout, "package.json"), "w", encoding="utf-8") as f:
        f.write("{}\n")
    agent_tools.install_dsh(local=checkout)
    assert fake_dsh["argv"][-1] == f"link:{checkout}"


def test_install_dsh_local_missing_checkout_errors(fake_dsh, fake_home, monkeypatch) -> None:
    monkeypatch.chdir(str(fake_home))
    result = agent_tools.install_dsh(local=True)
    assert "not found" in result
    assert "argv" not in fake_dsh


def test_install_dsh_missing_cli_errors(monkeypatch) -> None:
    monkeypatch.setattr(agent_tools.shutil, "which", lambda cmd: None)
    result = agent_tools.install_dsh()
    assert "dsh CLI not found" in result


def test_install_dsh_failure_includes_stderr(fake_dsh, monkeypatch) -> None:
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom\n")

    monkeypatch.setattr(agent_tools.subprocess, "run", fake_run)
    result = agent_tools.install_dsh()
    assert "failed" in result
    assert "boom" in result


# ---------------------------------------------------------------------------
# Legacy prompt install still works
# ---------------------------------------------------------------------------


def test_legacy_prompt_block_roundtrip(fake_home) -> None:
    """The prompt injection path (install prompt) writes/removes marker blocks."""
    path = _skill_path(fake_home, "AGENTS.md")
    status = agent_tools._write_prompt(path)
    assert status == "installed"
    assert agent_tools._prompt_installed_in(path)
    assert agent_tools._read_prompt_version(path) == __version__
    assert agent_tools._write_prompt(path) == "uptodate"
    assert agent_tools._remove_prompt(path) is True
    assert not os.path.exists(path)
