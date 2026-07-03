# graphlint Documentation

**graphlint** is a dead code detection tool for AI-generated codebases. AI agents produce large amounts of redundant code while generating rapidly, polluting the LLM context window and diluting attention. graphlint extracts code structure via AST parsing, builds a dependency graph, identifies entry points, and finds all unreachable dead code — enabling agents to self-analyze and self-clean their codebases.

## Quick Links

- [Getting Started](guide/getting-started.md) — Installation and basic usage
- [Agent Integration](guide/agent-integration.md) — Install prompt into agent tools
- [CLI Usage Guide](cli/usage.md) — Command-line tool reference
- [API Reference](api/query.md) — Python API documentation
- [Configuration Guide](guide/configuration.md) — Custom configuration
- [Architecture Overview](architecture/overview.md) — Project architecture and modules

## Core Features

| Feature | Description |
|---------|-------------|
| **Dead Code Detection** | Finds components unreachable from any entry point via graph traversal |
| **AST Parsing** | Extracts classes, functions, methods, variables, fields as nodes |
| **Dependency Graph** | Five edge types: read / write / call / inherit / decorate |
| **Entry Point Detection** | 10 built-in rules: main / package / fastapi / flask / django / click / typer / celery / pytest / pytest_test |
| **Warning Detection** | 11 warning types: circular refs, unused imports, write-only variables, dead code, and more |
| **Incremental Indexing** | SHA256-based change detection, parses only modified files |
| **Python API + CLI** | Integrate into any Tool pipeline, CI workflow, or let agents self-analyze and self-clean via CLI |

## Project Structure

```
graphlint/                 # Core package
├── __init__.py           # Package entry, lazy imports for public API
├── api.py                # Python API: query / build / configure
├── cli.py                # CLI entry: graphlint commands
├── params.py             # Shared parameter definitions (CLI + API)
├── exceptions.py         # Custom exception classes
├── analyzer/             # Parsing and analysis modules
│   ├── parser.py         # AST parser
│   ├── graph.py          # Graph builder
│   ├── entry_detect.py   # Entry point detection
│   ├── imports.py        # Import analysis
│   ├── decorators.py     # Decorator resolution
│   ├── warnings.py       # Warning collection
│   ├── _ast_visitor.py   # AST visitor
│   ├── _graph_algo.py    # Graph algorithms
│   └── _types.py         # Internal type definitions
├── config/               # Configuration management
│   ├── __init__.py       # Package entry
│   ├── defaults.py       # Default configuration
│   └── manager.py        # Configuration manager
├── i18n/                 # Internationalization
│   ├── __init__.py       # i18n manager
│   ├── en.py             # English translations
│   └── zh_CN.py          # Simplified Chinese translations
├── incremental/          # Incremental indexing
│   ├── indexer.py        # Incremental indexer
│   └── _db_ops.py        # Database operations
├── query/                # Query engine
│   ├── engine.py         # Query engine
│   ├── formatter.py      # Text formatting
│   └── volume.py         # Output volume strategy
└── storage/              # Persistence
    ├── db.py             # Database
    ├── hashing.py        # File hashing
    └── schema.py         # Database schema
```
