# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-07-01

### Added
- Initial release
- AST-based Python source code parsing (classes, functions, methods, variables, fields)
- Dependency graph construction with 5 edge types (read, write, call, inherit, decorate)
- 8 built-in entry point detection rules (main, FastAPI, Flask, Django, Click, Typer, Celery, pytest)
- Custom entry point rules via AST pattern matching
- 11 warning types (unused_import, dynamic_import, circular_ref, syntax_error, write_only, deprecated_usage, dead_code, type_mismatch, unresolved_ref, unused_variable, file_too_large)
- Incremental indexing with SHA256-based change detection
- Adaptive output volume strategy (full, index, truncated)
- Internationalization (English and Simplified Chinese)
- CLI interface (`graphlint query`, `graphlint build`, `graphlint config`)
- Python API (`query()`, `build()`, `configure()`)
- SQLite persistence with cross-platform file locking
- Parallel file parsing via ProcessPoolExecutor
- Configuration management with dot-notation key access
- Comprehensive test suite (unit, integration, performance)
