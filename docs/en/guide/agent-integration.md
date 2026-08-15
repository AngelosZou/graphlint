# Agent Integration

Graphlint supports three installation channels for AI coding agents:

1. **Skill install (default, recommended)** — writes the canonical skill document as `SKILL.md` into the emerging cross-agent skill directories. It does not touch your agent's own config files, and works with any agent that reads the `~/.agents/skills` convention.
2. **DeepSeek Harness plugin (recommended in DSH)** — installs the `dsh-graphlint` bundle (native tools + skill) into a DSH profile. The tool-based integration is more robust than a skill file alone: structured results, background job builds, and working-directory guards.
3. **Prompt injection** — injects the prompt block into agent config files (`AGENTS.md`, `CLAUDE.md`, …). Available as `install prompt`.

## Install the Skill (default, recommended)

```bash
graphlint install
# or explicitly: graphlint install skill
```

Writes `~/.agents/skills/graphlint/SKILL.md` (YAML frontmatter with `name`, `description` and a `version` field for update tracking).

| Option | Behavior |
|--------|----------|
| `--targets agents` (default) | `~/.agents/skills/graphlint/SKILL.md` |
| `--targets claude` | `~/.claude/skills/graphlint/SKILL.md` (Claude Code convention) |
| `--targets all` / `--targets agents,claude` | Both directories |

Re-running `install` reports `up to date` or upgrades an older installed version. The skill content is deliberately concise — only the broadly useful core:

| Section | Content |
|---------|---------|
| **Usage scenarios** | When to run graphlint — post-modification cleanup, pre-analysis audit |
| **Core commands** | `query` (auto incremental build), `query --json`, `query -g <id>`, `config show`; `build --force` only when query results look stale |
| **Key parameters** | `-g`/`--graph-id`, `-j`/`--json`, `-w`/`--warn-types`, `-C`, `-R`/`--reachability`, `--public-as-entry`, `-t`, `--dead-code-tests`, `--sort-by`, `--fail-on`, build `-f`/`-P` |
| **Custom entry rules** | `config add-entry-rule` / `remove-entry-rule` / `add-exclude` for framework-specific conventions |
| **Examples** | Refactor check, dead code by severity, graph detail, CI gate |
| **Limitations** | Static analysis only (dynamic references), full-build time cost |

## Install the DeepSeek Harness Plugin (recommended in DSH)

```bash
graphlint install dsh --profile web
```

Runs `dsh plugin --profile web add dsh-graphlint`. Use `--local [PATH]` to link a local `integrations/dsh` checkout instead of the npm package (defaults to `./integrations/dsh` from the repository root). Restart `dsh web` and refresh the browser page afterwards.

In the DSH environment the plugin's tools (`graphlint_query` / `graphlint_build` / `graphlint_config`) are the primary interface: they run inside the session working directory, return structured results, and refuse unsafe roots — the plugin registers its own `graphlint` skill alongside the tools, kept separate from the file-based `SKILL.md` install.

## Install the Prompt

```bash
graphlint install prompt
```

Interactive selector injecting the prompt block into global config files, wrapped in HTML comments (`<!-- graphlint:start -->` … `<!-- graphlint:end -->`) for clean detection and removal:

| Tool ID | Display Name | Global Config File |
|---------|-------------|-------------------|
| `opencode` | OpenCode CLI | `~/.config/opencode/AGENTS.md` |
| `cursor` | Cursor Editor | `~/.cursorrules` |
| `codex` | Codex CLI | `~/.codex/rules/graphlint.md` |
| `cc` | Claude Code (CLI) | `~/.claude/CLAUDE.md` |

## Prompt Command

If your agent tool is not listed or you prefer manual setup, copy the prompt to your clipboard:

```bash
graphlint prompt
```

This copies the same content that `install` would write — paste it into your agent's system prompt or configuration file.

## Uninstall

```bash
graphlint uninstall              # remove the installed skill(s)
graphlint uninstall --targets all
graphlint uninstall prompt       # remove injected prompt blocks
```

`uninstall` removes the `SKILL.md` written by graphlint (and its directory when empty); foreign files with the same path are left untouched. `uninstall prompt` scans the agent config paths for the marker block and removes it interactively.

## Single Content Source

The canonical skill document ships inside the Python package as `graphlint/skill.md` (with YAML frontmatter). All channels derive from it: `install` writes it verbatim (plus a `version` field), `prompt` strips the frontmatter, and the DeepSeek Harness plugin embeds the same body at build time — guarded by sync tests on both sides.
