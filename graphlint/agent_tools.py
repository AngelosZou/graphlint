# -*- coding: utf-8 -*-
"""Agent tool integration — install/uninstall graphlint prompts for AI coding tools.

Configures agent tools at the global level so graphlint's usage prompt is
available in every project the agent opens.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib import resources
from typing import List, Optional, Tuple

from graphlint import __version__

# ---------------------------------------------------------------------------
# Canonical skill document
# ---------------------------------------------------------------------------
# The agent-facing usage guidance lives in a single file — graphlint/skill.md —
# shipped as package data.  AGENT_PROMPT (used by `graphlint install` and
# `graphlint prompt`) is that file with its YAML frontmatter stripped, so the
# prompt, the DSH skill and future SKILL.md installs can never drift apart.

SKILL_FILENAME = "skill.md"


def load_skill_markdown() -> str:
    """Return the canonical skill.md content shipped with the package."""
    return (
        resources.files("graphlint")
        .joinpath(SKILL_FILENAME)
        .read_text(encoding="utf-8")
    )


def skill_body() -> str:
    """Return the canonical skill markdown with its YAML frontmatter stripped."""
    text = load_skill_markdown()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:].lstrip("\r\n")
    return text.strip() + "\n"


AGENT_PROMPT = skill_body()

MARKER_START = "<!-- graphlint:start -->"
MARKER_END = "<!-- graphlint:end -->"
VERSION_MARKER = "<!-- graphlint:version:"


def _prompt_block() -> str:
    return f"\n{MARKER_START}\n{VERSION_MARKER}{__version__} -->\n{AGENT_PROMPT}\n{MARKER_END}\n"


def _expand(path: str) -> str:
    """Expand ~ to home directory, normalize separators."""
    return os.path.normpath(os.path.expanduser(path))


# Tool definitions: (id, display_name, global_config_path, description)
# All paths use ~ which is expanded at install/uninstall time.
TOOLS: List[Tuple[str, str, str, str]] = [
    (
        "opencode",
        "OpenCode CLI",
        "~/.config/opencode/AGENTS.md",
        "Global AGENTS.md — read by opencode in every project",
    ),
    (
        "cursor",
        "Cursor Editor",
        "~/.cursorrules",
        "Global .cursorrules — applies to all Cursor projects",
    ),
    (
        "codex",
        "Codex CLI",
        "~/.codex/rules/graphlint.md",
        "Global rules directory — recognized by Codex CLI",
    ),
    (
        "cc",
        "Claude Code",
        "~/.claude/CLAUDE.md",
        "Global CLAUDE.md — read by Claude Code in every project",
    ),
]


def _prompt_installed_in(filepath: str) -> bool:
    if not os.path.isfile(filepath):
        return False
    with open(filepath, encoding="utf-8") as f:
        return MARKER_START in f.read()


def _read_prompt_version(filepath: str) -> str:
    if not os.path.isfile(filepath):
        return ""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()
    if VERSION_MARKER not in content:
        return ""
    start = content.index(VERSION_MARKER) + len(VERSION_MARKER)
    end = content.index(" -->", start)
    return content[start:end]


def _write_prompt(filepath: str) -> str:
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        if os.path.isfile(filepath) and _prompt_installed_in(filepath):
            installed_version = _read_prompt_version(filepath)
            if installed_version == __version__:
                return "uptodate"
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            start = content.index(MARKER_START)
            end = content.index(MARKER_END) + len(MARKER_END)
            new_block = _prompt_block()
            content = content[:start] + new_block + content[end:]
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return "updated"
        block = _prompt_block()
        if os.path.isfile(filepath):
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(block)
        else:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(block)
        return "installed"
    except OSError:
        return "failed"


def _remove_prompt(filepath: str) -> bool:
    if not os.path.isfile(filepath):
        return False
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        if MARKER_START not in content:
            return False
        start = content.index(MARKER_START)
        end = content.index(MARKER_END) + len(MARKER_END)
        new_content = content[:start] + content[end:]
        lines = new_content.splitlines(keepends=True)
        cleaned = []
        prev_empty = False
        for line in lines:
            if line.strip() == "":
                if prev_empty:
                    continue
                prev_empty = True
            else:
                prev_empty = False
            cleaned.append(line)
        while cleaned and cleaned[0].strip() == "":
            cleaned.pop(0)
        while cleaned and cleaned[-1].strip() == "":
            cleaned.pop()
        new_content = "".join(cleaned)
        if new_content.strip() == "":
            os.remove(filepath)
        else:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
        return True
    except (OSError, ValueError):
        return False


def _resolve_paths(cwd: Optional[str] = None) -> List[Tuple[str, str, str, str, str]]:
    """Resolve tool paths, expanded from ~."""
    resolved = []
    for tool_id, display_name, rel_path, desc in TOOLS:
        full_path = _expand(rel_path)
        resolved.append((tool_id, display_name, rel_path, full_path, desc))
    return resolved


def _prompt_selection(items: List[Tuple], prompt: str) -> List[Tuple]:
    """Prompt user to select from a numbered list. Supports Ctrl+C to cancel."""
    print()
    try:
        raw = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return []
    if raw.lower() in ("all", "a"):
        return list(items)
    if not raw:
        return []
    try:
        indices = [int(x.strip()) for x in raw.split(",")]
    except ValueError:
        return []
    selected = []
    for idx in indices:
        if 1 <= idx <= len(items):
            selected.append(items[idx - 1])
    return selected


def _select_tools(resolved: List[Tuple], _t=None) -> List[Tuple]:
    """Interactive multi-select prompt for agent tools."""
    title = _t("cli.install.select_title") if _t is not None else "Select agent tool(s) to install graphlint prompt:"
    print(f"\n{title}")
    for i, (_, display_name, rel_path, full_path, desc) in enumerate(resolved, 1):
        print(f"  [{i}] {display_name:<20} {rel_path}")
    prompt = (
        _t("cli.install.select_prompt")
        if _t is not None
        else "Enter numbers (comma separated), 'all' or leave empty to cancel: "
    )
    return _prompt_selection(list(resolved), prompt)


def install_tools(cwd: Optional[str] = None, _t=None) -> str:
    """Interactively install graphlint prompt to selected agent tools (global)."""
    resolved = _resolve_paths(cwd)

    updated_names: List[str] = []
    for tool_id, display_name, rel_path, full_path, desc in resolved:
        if _prompt_installed_in(full_path):
            installed_version = _read_prompt_version(full_path)
            if installed_version != __version__:
                try:
                    with open(full_path, encoding="utf-8") as f:
                        content = f.read()
                    start = content.index(MARKER_START)
                    end = content.index(MARKER_END) + len(MARKER_END)
                    content = content[:start] + _prompt_block() + content[end:]
                    with open(full_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    updated_names.append(display_name)
                except (OSError, ValueError):
                    pass

    if updated_names and _t is not None:
        print(_t("cli.install.auto_updated"))
        for name in updated_names:
            print(f"  - {name}")

    selected = _select_tools(resolved, _t)
    if not selected:
        return "No tools selected."
    results = []
    for tool_id, display_name, rel_path, full_path, desc in selected:
        status = _write_prompt(full_path)
        if status == "installed":
            results.append(f"  ✓ {display_name} -> {full_path}")
        elif status == "uptodate":
            results.append(f"  - {display_name} ({rel_path}) — already installed")
        else:
            if _prompt_installed_in(full_path):
                results.append(f"  - {display_name} ({rel_path}) — already installed")
            else:
                results.append(f"  ✗ {display_name} ({rel_path}) — failed to write")
    return "Install results:\n" + "\n".join(results)


def copy_prompt_to_clipboard() -> bool:
    """Copy AGENT_PROMPT content to the system clipboard."""
    try:
        if sys.platform == "win32":
            subprocess.run(["clip"], input=AGENT_PROMPT, text=True, check=True)
        elif sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=AGENT_PROMPT, text=True, check=True)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"], input=AGENT_PROMPT, text=True, check=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def uninstall_tools(cwd: Optional[str] = None, _t=None) -> str:
    """Interactively uninstall graphlint prompt from selected agent tools."""
    resolved = _resolve_paths(cwd)
    installed = [
        t for t in resolved if _prompt_installed_in(t[3])
    ]
    if not installed:
        return "No agent tools with graphlint prompt found."
    print("\nDetected installations:")
    for i, (tool_id, display_name, rel_path, full_path, desc) in enumerate(
        installed, 1
    ):
        print(f"  [{i}] {display_name:<20} {rel_path}")
    prompt = (
        _t("cli.uninstall.select_prompt")
        if _t is not None
        else "Enter numbers to uninstall (comma separated), 'all' or leave empty to cancel: "
    )
    selected = _prompt_selection(installed, prompt)
    if not selected:
        return "No tools selected."
    results = []
    for tool_id, display_name, rel_path, full_path, desc in selected:
        if _remove_prompt(full_path):
            results.append(f"  ✓ {display_name} ({rel_path}) — removed")
        else:
            results.append(f"  ✗ {display_name} ({rel_path}) — failed to remove")
    return "Uninstall results:\n" + "\n".join(results)


# ---------------------------------------------------------------------------
# Skill installation (agents-compatible SKILL.md files)
# ---------------------------------------------------------------------------
# `graphlint install skill` writes the canonical skill document into the
# emerging cross-agent skill directories (~/.agents/skills is the default
# convention; Claude Code uses ~/.claude/skills).  The installed copy carries
# a `version` field in its frontmatter so re-installs can report updates.

SKILL_TARGETS: dict[str, str] = {
    "agents": "~/.agents/skills/graphlint/SKILL.md",
    "claude": "~/.claude/skills/graphlint/SKILL.md",
}

_SKILL_MSG_FALLBACKS: dict[str, str] = {
    "cli.install.skill.installed": "✓ Installed graphlint skill v{version} -> {path}",
    "cli.install.skill.updated": "✓ Updated graphlint skill v{old} -> v{new} at {path}",
    "cli.install.skill.uptodate": "- graphlint skill already up to date at {path}",
    "cli.install.skill.failed": "✗ Failed to write {path}",
    "cli.install.dsh.not_found": "dsh CLI not found on PATH. Install the DeepSeek Harness first, then retry.",
    "cli.install.dsh.local_missing": "Local integrations/dsh not found at {path}. Run from the graphlint repository root or pass --local PATH.",
    "cli.install.dsh.done": "✓ dsh-graphlint plugin added to profile '{profile}'. Restart dsh web and refresh the browser page.",
    "cli.install.dsh.failed": "✗ dsh plugin install failed.",
    "cli.uninstall.skill.removed": "✓ Removed graphlint skill from {path}",
    "cli.uninstall.skill.not_found": "- No graphlint skill found at {path}",
    "cli.uninstall.skill.foreign": "- {path} exists but was not installed by graphlint — skipped",
}


def _skill_msg(_t, key: str, **kwargs: str) -> str:
    """Format a skill message via i18n when available, else the English fallback."""
    if _t is not None:
        return _t(key, **kwargs)
    return _SKILL_MSG_FALLBACKS.get(key, key).format(**kwargs)


def _resolve_skill_targets(raw: Optional[str]) -> List[Tuple[str, str]]:
    """Parse a targets string ('agents', 'claude', comma list, 'all') into (id, path)."""
    if not raw or raw.strip().lower() == "all":
        ids = list(SKILL_TARGETS)
    else:
        ids = [p.strip().lower() for p in raw.split(",") if p.strip()]
    unknown = [tid for tid in ids if tid not in SKILL_TARGETS]
    if unknown:
        raise ValueError(
            f"Unknown skill target(s): {', '.join(unknown)}. "
            f"Allowed: {', '.join(SKILL_TARGETS)}, all"
        )
    result = []
    for tid in ids:
        if tid not in [r[0] for r in result]:
            result.append((tid, SKILL_TARGETS[tid]))
    return result


def _skill_file_with_version() -> str:
    """Canonical skill.md with a `version` field injected into the frontmatter."""
    md = load_skill_markdown()
    end = md.find("\n---", 3)
    if end == -1:
        return md
    return md[:end] + f"\nversion: {__version__}\n" + md[end:]


def _read_skill_version(path: str) -> str:
    """Read the `version` field from an installed SKILL.md frontmatter."""
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(4096)
    except OSError:
        return ""
    if not head.startswith("---"):
        return ""
    end = head.find("\n---", 3)
    if end == -1:
        return ""
    for line in head[:end].splitlines():
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip()
    return ""


def install_skills(targets: str = "agents", _t=None) -> str:
    """Install the graphlint SKILL.md into the requested skill directories."""
    try:
        resolved = _resolve_skill_targets(targets)
    except ValueError as exc:
        return str(exc)
    results = []
    for tid, rel_path in resolved:
        full_path = _expand(rel_path)
        installed_version = _read_skill_version(full_path)
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(_skill_file_with_version())
        except OSError:
            results.append(_skill_msg(_t, "cli.install.skill.failed", path=full_path))
            continue
        if installed_version == "":
            results.append(
                _skill_msg(
                    _t,
                    "cli.install.skill.installed",
                    version=__version__,
                    path=full_path,
                )
            )
        elif installed_version == __version__:
            results.append(_skill_msg(_t, "cli.install.skill.uptodate", path=full_path))
        else:
            results.append(
                _skill_msg(
                    _t,
                    "cli.install.skill.updated",
                    old=installed_version,
                    new=__version__,
                    path=full_path,
                )
            )
    return "Install results:\n" + "\n".join(results)


def _remove_skill_file(path: str) -> Optional[bool]:
    """Remove an installed SKILL.md (and its dir when empty).

    Returns True when removed, False when nothing to do, None when the file
    exists but was not installed by graphlint.
    """
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(512)
    except OSError:
        return False
    if "name: graphlint" not in head:
        return None
    try:
        os.remove(path)
        try:
            os.rmdir(os.path.dirname(path))
        except OSError:
            pass
        return True
    except OSError:
        return False


def uninstall_skills(targets: str = "agents", _t=None) -> str:
    """Remove the graphlint SKILL.md from the requested skill directories."""
    try:
        resolved = _resolve_skill_targets(targets)
    except ValueError as exc:
        return str(exc)
    results = []
    for tid, rel_path in resolved:
        full_path = _expand(rel_path)
        outcome = _remove_skill_file(full_path)
        if outcome is True:
            results.append(_skill_msg(_t, "cli.uninstall.skill.removed", path=full_path))
        elif outcome is None:
            results.append(_skill_msg(_t, "cli.uninstall.skill.foreign", path=full_path))
        else:
            results.append(_skill_msg(_t, "cli.uninstall.skill.not_found", path=full_path))
    return "Uninstall results:\n" + "\n".join(results)


# ---------------------------------------------------------------------------
# DeepSeek Harness plugin installation
# ---------------------------------------------------------------------------


def install_dsh(profile: Optional[str] = None, local=None, _t=None) -> str:
    """Install the dsh-graphlint plugin into a DeepSeek Harness profile.

    *profile* is the dsh profile name (``--profile`` is omitted when None).
    *local* is None (npm package), True (link ./integrations/dsh from cwd),
    or an explicit path to a local integrations/dsh checkout.
    """
    dsh = shutil.which("dsh")
    if not dsh:
        return _skill_msg(_t, "cli.install.dsh.not_found")

    if local is None:
        target = "dsh-graphlint"
    else:
        if local is True:
            local_path = os.path.normpath(os.path.join(os.getcwd(), "integrations", "dsh"))
        else:
            local_path = os.path.normpath(os.path.abspath(str(local)))
        if not os.path.isfile(os.path.join(local_path, "package.json")):
            return _skill_msg(_t, "cli.install.dsh.local_missing", path=local_path)
        target = f"link:{local_path}"

    cmd = [dsh, "plugin"]
    if profile:
        cmd += ["--profile", profile]
    cmd += ["add", target]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )
    except subprocess.TimeoutExpired:
        return _skill_msg(_t, "cli.install.dsh.failed") + "\n(command timed out)"
    except OSError:
        return _skill_msg(_t, "cli.install.dsh.failed")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return _skill_msg(_t, "cli.install.dsh.failed") + (f"\n{detail}" if detail else "")
    return _skill_msg(_t, "cli.install.dsh.done", profile=profile or "default")
