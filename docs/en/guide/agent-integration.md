# Agent Integration

Graphlint provides `install` and `uninstall` subcommands to inject its usage prompt into your AI coding tools at the **global level**. Once installed, every project you open with that tool will have graphlint's guidance available — no per-project setup needed.

## Install

```bash
graphlint install
```

You will see an interactive prompt listing supported tools and their global config paths:

```
Select agent tool(s) to install graphlint prompt:

  [1] OpenCode CLI          ~/.config/opencode/AGENTS.md
      Global AGENTS.md — read by opencode in every project
  [2] Cursor Editor         ~/.cursorrules
      Global .cursorrules — applies to all Cursor projects
  [3] Codex CLI             ~/.codex/rules/graphlint.md
      Global rules directory — recognized by Codex CLI
  [4] Claude Code (CLI)     ~/.claude/CLAUDE.md
      Global CLAUDE.md — read by Claude Code in every project

Enter numbers separated by comma (e.g. 1,3) or 'all':
```

Select one or more tools. The prompt block is wrapped in HTML comments (`<!-- graphlint:start -->` … `<!-- graphlint:end -->`) for clean detection and removal.

### What Gets Installed

The prompt includes only what an agent needs — no fluff:

| Section | Content |
|---------|---------|
| **Usage scenarios** | When to run graphlint — post-modification cleanup, pre-analysis audit |
| **Quick commands** | `build`, `query`, `config` — the essential commands |
| **Key parameters** | `-g`/`--graph-id`, `--json`, `-w`/`--warn-types`, `-t`, `-d`, `-r`, `-C`, `-f`, `--sort-by` |
| **Examples** | Dead code detection, graph detail, filtered queries, typical workflow |

## Uninstall

```bash
graphlint uninstall
```

Scans the global config paths for the `graphlint:start`/`graphlint:end` markers and shows which tools have the prompt installed. Select the ones to remove.

## Prompt File

The canonical prompt is also stored at `.graphlint/agent-prompt.md` in each project's metadata directory for manual review.

## Supported Tools

| Tool ID | Display Name | Global Config File |
|---------|-------------|-------------------|
| `opencode` | OpenCode CLI | `~/.config/opencode/AGENTS.md` |
| `cursor` | Cursor Editor | `~/.cursorrules` |
| `codex` | Codex CLI | `~/.codex/rules/graphlint.md` |
| `cc` | Claude Code (CLI) | `~/.claude/CLAUDE.md` |

> **Note:** These are **global** config paths. If you prefer per-project installation, manually copy the prompt block from `.graphlint/agent-prompt.md` into your project's local config file (e.g., `AGENTS.md`, `CLAUDE.md`, `.cursorrules`).
