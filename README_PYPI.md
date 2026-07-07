# graphlint

[![PyPI](https://img.shields.io/pypi/v/graphlint)](https://pypi.org/project/graphlint/)
[![Python](https://img.shields.io/pypi/pyversions/graphlint)](https://pypi.org/project/graphlint/)
[![License](https://img.shields.io/pypi/l/graphlint)](https://github.com/AngelosZou/graphlint/blob/main/LICENSE)

[![en](https://img.shields.io/badge/lang-en-red.svg)](https://github.com/AngelosZou/graphlint/blob/main/README.md)
[![zh](https://img.shields.io/badge/lang-zh--CN-blue.svg)](https://github.com/AngelosZou/graphlint/blob/main/docs/zh/README.md)

**Dead code detection for AI-generated Python codebases.**

AI agents generate code rapidly, leaving behind dead and redundant code that pollutes the LLM's context window and dilutes attention. Graphlint analyzes your Python codebase's dependency graph to identify entry points and **detect dead code** — components unreachable from any entry point — so agents can self-clean and keep the codebase lean.

## Features

- **Dead code detection** — finds components unreachable from any entry point via graph traversal
- **AST parsing** — extracts classes, functions, methods, variables, and fields
- **Dependency graph** — builds directed edges: `read`, `write`, `call`, `inherit`, `decorate`
- **Entry point detection** — 10 built-in rules (main, FastAPI, Flask, Django, Click, Typer, Celery, pytest, plus package and test entries) and custom rules
- **Warning detection** — 11 warning types including circular references, unused imports, write-only variables, and more
- **Python API + CLI** — integrate into any Tool, CI pipeline, or let agents self-analyze and self-clean

## Installation

```bash
pip install graphlint
```

**Requirements:** Python >= 3.9

## Quick Start

### Agent Integration

Graphlint provides a command to inject its usage prompt into your AI coding tools at the **global level**, so every project automatically has graphlint's guidance:

```bash
# Install graphlint prompt into agent tools (opencode, cursor, codex, cc)
graphlint install

# Copy the prompt to clipboard for manual paste into your agent
graphlint prompt

# Remove graphlint prompt from agent tools
graphlint uninstall
```

Run `graphlint install` and select the tools you use — the prompt (usage scenarios, essential commands, and parameters) will be added to their global configuration. For details, see [Agent Integration](https://github.com/AngelosZou/graphlint/blob/main/docs/en/guide/agent-integration.md).

### CLI

```bash
# Find dead code in current directory
graphlint query --warn-types "dead_code"

# Full analysis with JSON output
graphlint query --json

# View a specific graph detail
graphlint query -g 1 --detail full

# Rebuild index
graphlint build --force

# Configure
graphlint config show
graphlint config set --key lang --value en
```

### Python API

```python
from graphlint.api import query

# Find dead code components
result = query(warn_types="dead_code", json_output=True)

# Full dependency graph analysis
result = query(include_tests=True, json_output=True)
```

## Warning Types

| Warning | Description |
|---------|-------------|
| `unused_import` | Imported module or name is never used |
| `dynamic_import` | Dynamic import via `importlib` or `__import__` |
| `circular_ref` | Circular dependency between functions/classes |
| `syntax_error` | File contains a syntax error |
| `write_only` | Variable is written but never read |
| `deprecated_usage` | Usage of a deprecated function/class |
| `dead_code` | Component unreachable from any entry point |
| `type_mismatch` | Suspicious type annotations |
| `unresolved_ref` | Reference to an undefined name |
| `unused_variable` | Variable is defined but never used |
| `file_too_large` | File exceeds the configured size limit |

## Development

```bash
# Clone the repository
git clone https://github.com/AngelosZou/graphlint.git
cd graphlint

# Create a virtual environment
python -m venv env
env/Scripts/activate  # Windows
source env/bin/activate  # Unix

# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=graphlint

# Run type checking
mypy graphlint/

# Run linting
ruff check graphlint/ tests/
```

## Configuration

Graphlint stores its configuration in `.graphlint/config.json` within the analyzed directory. Use `graphlint config` commands to manage settings, or edit the file directly.

See `graphlint config show` for the full default configuration.

## Documentation

Full documentation is available in the [docs/](https://github.com/AngelosZou/graphlint/tree/main/docs/) directory:

- [Getting Started](https://github.com/AngelosZou/graphlint/blob/main/docs/en/guide/getting-started.md)
- [Agent Integration](https://github.com/AngelosZou/graphlint/blob/main/docs/en/guide/agent-integration.md)
- [Configuration Guide](https://github.com/AngelosZou/graphlint/blob/main/docs/en/guide/configuration.md)
- [Entry Point Detection](https://github.com/AngelosZou/graphlint/blob/main/docs/en/guide/entry-detection.md)
- [Warning Reference](https://github.com/AngelosZou/graphlint/blob/main/docs/en/guide/warnings.md)
- [CLI Usage](https://github.com/AngelosZou/graphlint/blob/main/docs/en/cli/usage.md)
- [Architecture Overview](https://github.com/AngelosZou/graphlint/blob/main/docs/en/architecture/overview.md)
- [Python API](https://github.com/AngelosZou/graphlint/tree/main/docs/en/api/)

## Limitations

- **Static analysis only** — graphlint performs static analysis and cannot detect runtime linkage such as `getattr`, `importlib`, or dynamic dispatch patterns, which may result in false positives. **Mitigation:** add custom entry rules matching your codebase's conventions. For example, graphlint's own codebase uses `function_def:_detect_*` and `function_def:visit_*` patterns to prevent functions discovered via `getattr` from being flagged as dead.
- **Large codebase build time** — on a large codebase with 700+ `.py` files, 1,000+ classes, and 14,000+ functions, a full rebuild takes approximately 200 seconds (actual performance depends on hardware). Small projects (~60 files) complete in ~1 second. **Best practice:** run `query` before making changes to plan your work, and avoid invoking `query` during refactoring to prevent unnecessary index rebuilds.

## License

MIT — see [LICENSE](https://github.com/AngelosZou/graphlint/blob/main/LICENSE) for details.

## Links

- [GitHub Repository](https://github.com/AngelosZou/graphlint)
- [Issue Tracker](https://github.com/AngelosZou/graphlint/issues)
- [PyPI Package](https://pypi.org/project/graphlint/)
