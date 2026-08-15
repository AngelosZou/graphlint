# CLI Usage Guide

The `graphlint` command-line tool provides six subcommands: `query`, `build`, `install`, `uninstall`, `prompt`, and `config`.

## Global Options

```
usage: graphlint [-h] {query,build,install,uninstall,prompt,config} ...
```

- `-h, --help` — Show help message

## query — Query Dependency Graph

The query subcommand retrieves and analyzes the code dependency graph.

### Basic Usage

```bash
graphlint query                    # Analyze current directory
graphlint query -r /path/to/proj   # Analyze a specific project
graphlint query -j                 # JSON format output
```

### Options Reference

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--include-tests` | `-t` | flag | `false` | Include nodes from test files |
| `--exclude-clean` | `-C` | flag | `false` | Exclude graphs with no issues (show only warnings/errors) |
| `--reachability` | `-R` | flag | `false` | Return only graphs reachable from entry points via CALL edges |
| `--dead-code-tests` | — | flag | `false` | Query tests referencing dead code |
| `--graph-id` | `-g` | int | — | View detailed info for a specific graph |
| `--json` | `-j` | flag | `false` | Structured JSON output |
| `--path-format` | `-p` | choice | `relative` | Path format: `absolute` / `relative` |
| `--root-dir` | `-r` | string | `.` | Target project root directory |
| `--max-results` | `-n` | int | `50` | Max graphs returned (1–1000) |
| `--min-nodes` | — | int | `0` | Only return graphs with ≥ N nodes |
| `--max-nodes` | — | int | — | Only return graphs with ≤ N nodes |
| `--warn-types` | `-w` | string | — | Comma-separated warning type filter |
| `--sort-by` | — | choice | `warnings` | Sort by: `warnings` / `nodes` / `edges` / `name` |
| `--detail` | `-d` | choice | `auto` | Detail level: `auto` / `summary` / `full` / `minimal` |
| `--output-limit` | — | int | `8000` | Output text length limit (chars, 100–100000) |
| `--edge-limit` | — | int | `10` | Max edges shown in graph detail (0=unlimited) |
| `--file-limit` | — | int | `10` | Max files shown in graph detail (0=unlimited) |
| `--node-limit` | — | int | `30` | Max nodes shown in graph detail (0=unlimited) |
| `--no-scan` | — | flag | `false` | Skip auto-scan/build, query existing index only |
| `--public-as-entry` | — | flag | `false` | Treat public methods (Rust `pub`, C# `public`) as execution entry points — see [Entry Detection](../guide/entry-detection.md#--public-as-entry-flag) |
| `--fail-on` | — | string | — | Exit non-zero if matching warning types found (comma-separated) |

### Examples

```bash
# View full details of graph 3
graphlint query -g 3 --detail full

# Show only graphs with 5+ nodes, sorted by warning count
graphlint query --min-nodes 5 --sort-by warnings

# Query only circular reference warnings
graphlint query -w "circular_ref"

# No auto-scan mode (for read-only queries)
graphlint query --no-scan

# Fail with exit code 2 when dead code or circular refs found
graphlint query --json --fail-on dead_code,circular_ref
```

### Exit Codes

The `query` subcommand returns the following exit codes:

| Code | Meaning |
|------|---------|
| `0` | Success — no warnings matched `--fail-on` |
| `1` | Error — invalid parameters, exception, or config error |
| `2` | Warnings found — `--fail-on` matched specified warning types |

Use `--fail-on` with a comma-separated list of warning types to fail the command when matching warnings exist. This enables CI pipeline integration:

```bash
# CI pipeline: fail if dead code or circular refs found
graphlint query --json --fail-on dead_code,circular_ref || exit 1
```

## install — Install for Agent Tools

Installs graphlint support for AI coding agents. Without a subcommand, the **skill** is installed into the cross-agent skill directories.

### Usage

```bash
graphlint install                        # skill (default)
graphlint install skill --targets agents # ~/.agents/skills/graphlint/SKILL.md
graphlint install skill --targets all    # agents + claude directories
graphlint install dsh --profile web      # dsh plugin add dsh-graphlint
graphlint install prompt                 # legacy prompt injection
```

`install skill` writes the canonical `graphlint/skill.md` (with a `version` frontmatter field) and reports `installed` / `updated` / `up to date` on re-runs. `install dsh` requires the `dsh` CLI on PATH; `--local [PATH]` links a local `integrations/dsh` checkout. See [Agent Integration](../guide/agent-integration.md).

## uninstall — Remove Installed Skills/Prompts

Removes previously installed graphlint skills or prompt blocks.

### Usage

```bash
graphlint uninstall                        # skill (default)
graphlint uninstall skill --targets all
graphlint uninstall prompt                 # legacy prompt removal
```

`uninstall` removes only the `SKILL.md` files written by graphlint (foreign files at the same path are left untouched); `uninstall prompt` scans the legacy config paths for marker blocks and removes them interactively.

## prompt — Copy Prompt to Clipboard

Copy graphlint's agent prompt to the system clipboard so you can manually paste it into your agent's configuration.

### Usage

```bash
graphlint prompt
```

If clipboard access succeeds, a confirmation message is shown. If it fails (e.g., no clipboard tool available), the prompt text is printed to stdout instead.

## build — Build/Rebuild Index

The build subcommand scans files and builds or updates the dependency graph index.

### Basic Usage

```bash
graphlint build              # Incremental build
graphlint build --force      # Full rebuild
graphlint build -P 4         # 4 parallel workers
```

### Options Reference

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--force` | `-f` | flag | `false` | Force full rebuild (ignore incremental cache) |
| `--parallel` | `-P` | int | `0` | Parallel workers (0=auto-detect CPU, max 64) |

### Output

Build returns JSON-formatted statistics:

```json
{
  "status": "ok",
  "files_scanned": 150,
  "files_changed": 12,
  "files_added": 3,
  "files_removed": 1,
  "nodes_added": 45,
  "edges_updated": 120,
  "duration_ms": 320,
  "warnings_generated": 8
}
```

## config — Configuration Management

The config subcommand views and modifies the `.graphlint/config.json` configuration file.

### Subcommands

| Command | Description |
|---------|-------------|
| `show` | Display current configuration |
| `get --key <key>` | Get the value of a specific config key |
| `set --key <key> --value <val>` | Set a specific config value |
| `copy-from --from <source>` | Copy config from a source directory |
| `add-entry-rule --rule-json <json>` | Add a custom entry detection rule |
| `remove-entry-rule --name <name>` | Remove an entry detection rule |
| `add-exclude --exclude-pattern <pat>` | Add an exclude pattern |
| `remove-exclude --exclude-pattern <pat>` | Remove an exclude pattern |

### Examples

```bash
# Show configuration
graphlint config show

# Switch language
graphlint config set --key lang --value en

# Add custom entry rule
graphlint config add-entry-rule --rule-json '{"name":"my_cli","ast_pattern":"class_instantiation:click.Group","file_pattern":"**/cli.py","enabled":true}'

# Add exclude pattern
graphlint config add-exclude --exclude-pattern "migrations/"
```
