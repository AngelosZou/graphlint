# Getting Started

graphlint targets the problem of redundant code in AI agent-generated codebases. It analyzes your codebase's dependency graph to find dead code — components unreachable from any entry point. This dead code pollutes the LLM context window and dilutes attention, making it a key target for agent self-cleaning.

graphlint provides a **Python API** (for integration into any Tool development) and a **CLI** (for CI pipelines or direct agent invocation for self-analysis and cleanup).

## Installation

```bash
pip install graphlint
```

Requirements: Python >= 3.9, zero third-party dependencies.

## Agent Integration

Graphlint can inject its usage prompt directly into your AI coding tools at the **global level**, so every project automatically has graphlint's guidance:

```bash
# Interactive: install prompt to one or more agent tools
graphlint install

# Interactive: remove prompt from agent tools
graphlint uninstall
```

During `install`, you will be prompted to select from supported tools and their global config paths:

| Tool | Global Config File |
|------|-------------------|
| **OpenCode CLI** | `~/.config/opencode/AGENTS.md` |
| **Cursor Editor** | `~/.cursorrules` |
| **Codex CLI** | `~/.codex/rules/graphlint.md` |
| **Claude Code (CLI)** | `~/.claude/CLAUDE.md` |

The installed prompt covers usage scenarios (post-modification cleanup, pre-analysis audit), essential commands (`query`, `build`, `config`), core parameters (`-g`, `--json`, `-w`, `-d`, etc.), and examples.

See [Agent Integration](agent-integration.md) for details.

## CLI Quick Start

### Query the Dependency Graph

```bash
# Analyze current directory, list dependency graphs
graphlint query

# JSON format output
graphlint query --json

# View a specific graph in detail
graphlint query -g 1 --detail full

# Include test files
graphlint query --include-tests

# Limit max results
graphlint query --max-results 10

# Sort by node count
graphlint query --sort-by nodes

# Filter by warning types
graphlint query --warn-types "circular_ref,unused_import"

# CI pipeline: exit non-zero when dead code found
graphlint query --json --fail-on dead_code,circular_ref
```

### Build / Rebuild Index

```bash
# Incremental build (parse only changed files)
graphlint build

# Force full rebuild
graphlint build --force

# Parallel build (auto-detect CPU cores)
graphlint build --parallel 0
```

### Configuration Management

```bash
# View current configuration
graphlint config show

# Set language to English
graphlint config set --key lang --value en

# Get a config value
graphlint config get --key lang

# Copy config from another directory
graphlint config copy-from --from /path/to/project

# Add an entry detection rule
graphlint config add-entry-rule --rule-json '{"name":"my_app","ast_pattern":"function_call:my_entry","file_pattern":"**/main.py"}'

# Remove an entry rule
graphlint config remove-entry-rule --name my_app

# Add an exclude pattern
graphlint config add-exclude --exclude-pattern "generated/"

# Remove an exclude pattern
graphlint config remove-exclude --exclude-pattern "generated/"
```

## Python API Quick Start

### Basic Query

```python
from graphlint.api import query, build, configure

# Query dependency graph (text format)
result = query()
print(result)

# Query dependency graph (JSON format)
result = query(
    include_tests=True,
    json_output=True,
    max_results=20,
    sort_by="warnings",
)
print(result)

# Query specific graph details
detail = query(graph_id=1, detail_level="full", json_output=True)
print(detail)
```

### Build Index

```python
from graphlint.api import build

# Incremental build
stats = build()
print(f"Files scanned: {stats['files_scanned']}")
print(f"Files changed: {stats['files_changed']}")
print(f"Nodes added: {stats['nodes_added']}")

# Force rebuild
stats = build(force_rebuild=True, parallel=4)
```

### Configuration Management

```python
from graphlint.api import configure

# View configuration
result = configure(action="show")
print(result["config"])

# Set configuration
configure(action="set", key="lang", value="en")

# Get a config value
result = configure(action="get", key="lang")
print(result["value"])
```

### Lazy Import

The `graphlint` package supports lazy imports — modules are loaded only on first access:

```python
import graphlint

# __version__ is a module constant, directly accessible
print(graphlint.__version__)  # "0.1.4"

# query / build / configure are lazily imported on first access
result = graphlint.query()       # Lazy-loaded on first call
stats = graphlint.build()        # Same
cfg = graphlint.configure(action="show")
```

## More Examples

### In CI/CD

```bash
#!/bin/bash
# Check for circular references
graphlint query --warn-types "circular_ref" --json | grep -q "circular_ref" && echo "Found circular refs!" || echo "Pass"
```

### Integration with Code Quality Tools

```python
from graphlint.api import query

# Check unused imports
result = query(
    warn_types="unused_import",
    json_output=True,
)

# Analyze results
if isinstance(result, dict):
    for graph in result.get("graphs", []):
        if graph.get("warnings"):
            print(f"Graph #{graph['graph_id']}({graph['name']}): {len(graph['warnings'])} warnings")
```
