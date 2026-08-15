# -*- coding: utf-8 -*-
"""Tests for the canonical skill document and its single-source derivation."""

from __future__ import annotations

from importlib import resources

from graphlint import __version__, agent_tools


def _canonical() -> str:
    return (
        resources.files("graphlint")
        .joinpath("skill.md")
        .read_text(encoding="utf-8")
    )


def _strip_frontmatter(text: str) -> str:
    assert text.startswith("---"), "skill.md must start with YAML frontmatter"
    end = text.find("\n---", 3)
    assert end != -1, "skill.md: unterminated YAML frontmatter"
    return text[end + 4:]


def test_canonical_frontmatter_declares_name_and_description() -> None:
    fm = _canonical()[: _canonical().find("\n---", 3)]
    assert "name: graphlint" in fm
    assert "description:" in fm


def test_agent_prompt_equals_stripped_canonical_body() -> None:
    expected = _strip_frontmatter(_canonical()).strip() + "\n"
    assert agent_tools.AGENT_PROMPT == expected
    assert agent_tools.AGENT_PROMPT == agent_tools.skill_body()


def test_prompt_block_wraps_prompt_with_markers_and_version() -> None:
    block = agent_tools._prompt_block()
    assert agent_tools.MARKER_START in block
    assert agent_tools.MARKER_END in block
    assert f"<!-- graphlint:version:{__version__} -->" in block
    assert agent_tools.AGENT_PROMPT.strip() in block


def test_canonical_body_covers_current_cli_surface() -> None:
    body = _strip_frontmatter(_canonical())
    for needle in (
        "graphlint query",
        "graphlint build --force",
        "--warn-types",
        "--reachability",
        "--public-as-entry",
        "--fail-on",
        "add-entry-rule",
        "getattr",
        "importlib",
        "~200 s",
    ):
        assert needle in body, f"canonical body must mention: {needle}"
    # The skill guidance is concise — guard against doc-style bloat.
    assert len(body) < 5000, "canonical body should stay concise"
