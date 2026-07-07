# -*- coding: utf-8 -*-
"""Agent tool integration — install/uninstall graphlint prompts for AI coding tools.

Configures agent tools at the global level so graphlint's usage prompt is
available in every project the agent opens.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Optional, Tuple

from graphlint import __version__

AGENT_PROMPT = """# graphlint — Dead Code Detection for Python

## When to Use It
- **After code modifications**: **Always** use graphlint check if your edits left behind dead or redundant code — components no longer reachable from any entry point
- **Before analyzing a codebase**: **Always** use graphlint to understand whether a feature is well integrated in the codebase.
- If you are unable to use the CLI, you should declare that you can not use graphlint for dead code detect.

## Quick Commands
```bash
graphlint build --force              # Build/rebuild index (Full codebase scan, time consuming for large codebase)
graphlint query                      # List dependency graphs (recommanded, auto incremental rebuild)
graphlint query --json               # JSON output
graphlint query -g <id> --detail full  # Full detail on one graph
graphlint config show                # View current config
```

Use the -h option in each command to query detailed instructions (use only when necessary).

## Key Parameters
- `-g, --graph-id <int>` — Inspect a specific dependency graph
- `--json, -j` — Structured output (JSON)
- `-w, --warn-types <str>` — Filter: `dead_code`, `circular_ref`, `unused_import`
- `-t, --include-tests` — Include test files in analysis
- `-d, --detail <level>` — Detail: `auto`/`summary`/`full`/`minimal`
- `-r, --root-dir <path>` — Project root directory
- `-C, --exclude-clean` — Show only graphs with issues
- `-f, --force` — Force full index rebuild
- `--sort-by <field>` — Sort: `warnings`/`nodes`/`edges`/`name`

## Usage Examples
```bash
# Check for dead code after a refactor
graphlint query --json

# Inspect a specific component's connections
graphlint query -g 5 -d full

# Scan all warnings sorted by severity
graphlint query -C --sort-by warnings --json
```

## Limitations
- **Static analysis only** — graphlint cannot detect runtime linkage (`getattr`, `importlib`, etc.) or dynamic dispatch patterns. May cause false positives. Mitigation: add custom entry rules matching your codebase's conventions. For example, graphlint's own codebase uses `function_def:_detect_*` and `function_def:visit_*` patterns to prevent functions discovered via `getattr` from being flagged as dead.
- **Large codebase build time** — a full rebuild on 700+ `.py` files / 1,000+ classes / 14,000+ functions takes ~200s (hardware-dependent). Small codebases (~60 files) complete in ~1s. Best practice: run `query` before making changes to plan, and avoid invoking `query` during refactoring to prevent unnecessary index rebuilds.\
"""

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
