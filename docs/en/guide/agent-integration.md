# Agent Integration

Graphlint provides `install` and `uninstall` subcommands to inject its usage prompt into your AI coding tools at the **global level**. Once installed, every project you open with that tool will have graphlint's guidance available — no per-project setup needed.

## Prompt Command

If your agent tool is not listed or you prefer manual setup, copy the prompt to your clipboard:

```bash
graphlint prompt
```

This copies the same `AGENT_PROMPT` content that `install` would write — paste it into your agent's system prompt or configuration file.

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

The prompt is deliberately concise — only the broadly useful core:

| Section | Content |
|---------|---------|
| **Usage scenarios** | When to run graphlint — post-modification cleanup, pre-analysis audit |
| **Core commands** | `query` (auto incremental build), `query --json`, `query -g <id>`, `config show`; `build --force` only when query results look stale |
| **Key parameters** | `-g`/`--graph-id`, `-j`/`--json`, `-w`/`--warn-types`, `-C`, `-R`/`--reachability`, `--public-as-entry`, `-t`, `--dead-code-tests`, `--sort-by`, `--fail-on`, build `-f`/`-P` |
| **Custom entry rules** | `config add-entry-rule` / `remove-entry-rule` / `add-exclude` for framework-specific conventions |
| **Examples** | Refactor check, dead code by severity, graph detail, CI gate |
| **Limitations** | Static analysis only (dynamic references), full-build time cost |

## Uninstall

```bash
graphlint uninstall
```

Scans the global config paths for the `graphlint:start`/`graphlint:end` markers and shows which tools have the prompt installed. Select the ones to remove.

## Prompt File

The canonical skill document ships inside the Python package as `graphlint/skill.md` (with YAML frontmatter). `install` and `prompt` derive their text from it — the frontmatter is stripped — so every distribution channel shares one source.

## Supported Tools

| Tool ID | Display Name | Global Config File |
|---------|-------------|-------------------|
| `opencode` | OpenCode CLI | `~/.config/opencode/AGENTS.md` |
| `cursor` | Cursor Editor | `~/.cursorrules` |
| `codex` | Codex CLI | `~/.codex/rules/graphlint.md` |
| `cc` | Claude Code (CLI) | `~/.claude/CLAUDE.md` |

> **Note:** These are **global** config paths. If you prefer per-project installation, copy the prompt block from `graphlint prompt` (or the canonical `graphlint/skill.md` in the installed package) into your project's local config file (e.g., `AGENTS.md`, `CLAUDE.md`, `.cursorrules`).
