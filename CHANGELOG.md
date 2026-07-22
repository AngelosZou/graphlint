# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0] - 2026-07-22

### Added
- Multi-language architecture: `LanguageAdapter` abstract base class and
  `LanguageRegistry` for extension-based routing of source files to language
  backends, laying the foundation for future multi-language support
- `language/python/` package: Python-specific adapter, parser, entry detector,
  imports analyzer, decorators resolver, and constants — decoupled from the
  core framework
- Per-language `constants.py`: configurable public API dunders, special
  methods, and test-file detection
- Type annotation awareness in AST visitor: automatically resolves unpacked
  variable types (e.g., loop bindings, tuple unpacking) for more accurate
  read/write edge tracking

### Changed
- **[Breaking]** Analyzer modules reorganized: `parser.py`, `entry_detect.py`,
  `imports.py`, `decorators.py`, `visitor.py` moved into `language/python/` —
  direct imports of old module paths will break
- Entry point rules now serve as initialization template only: rules are
  written to `.graphlint/config.json` on first build, after which the config
  file is the single source of truth
- Default entry strategy simplified: entry rules are no longer hardcoded in
  the indexer; they come solely from runtime configuration
- `GraphBuilder` no longer owns entry detection — entry points are resolved
  through the language adapter
- `WarningCollector` simplified: language-specific constant tables moved to
  `language/python/constants.py`

## [0.1.12] - 2026-07-21

### Added
- `query --fail-on <warn-types>` option: returns exit code `2` when matching
  warning types are found in query results, enabling CI pipeline integration
- `graphlint config` subcommands now return exit code `1` on error (previously
  always returned `0`)

## [0.1.11] - 2026-07-21

### Changed
- Entry point detection now uses a unified pattern-driven architecture — all
  rules (built-in and custom) share the same `_detect_custom` code path
- Built-in detectors replaced with declarative `ast_pattern` expressions using
  the existing prefix syntax (`function_call:`, `decorator:`, `if_name_main`,
  `file_match:`, `test_file`)
- `ast_pattern` supports OR combinations with ` | ` separator (e.g.
  `class_instantiation:FastAPI | function_call:uvicorn.run`)
- `ast_pattern` field is no longer required for entry rules — rules without
  it are silently skipped instead of failing validation
- Decorator matching uses `fnmatch` instead of substring `in`, providing
  precise glob matching and eliminating false positives from partial name
  overlaps
- `function_call:` and `class_instantiation:` patterns now support `fnmatch`
  globs (was exact match only)

### Fixed
- `file_match:` pattern now correctly checks the file path at rule level
  instead of a non-existent `node.filename` attribute, fixing the bug where
  `file_match:` rules never matched
- `graphlint config copy-from` no longer picks up irrelevant query/analyzer
  parameters, fixing the config copy command exception

## [0.1.10] - 2026-07-09

### Fixed
- Assignment target context resolution now correctly distinguishes class fields
  (`self.xxx` / `cls.xxx`), method-local variables, and module-level variables,
  preventing misclassification of `self.x = y` inside methods as local variables
- Class fields assigned across multiple methods (e.g. `__init__` + `set_x`) are
  now deduplicated to a single node, eliminating duplicate field nodes

### Changed
- Attribute-write edges (`self.xxx = value`) now also emit a `read` edge on
  the parent object (`self`), ensuring proper usage tracking of the containing
  class instance

## [0.1.9] - 2026-07-08

### Fixed
- FOREIGN KEY constraint failure on incremental rebuilds — prebuilt edge
  remapping now correctly writes remapped node IDs into edge objects
- `_insert_nodes` node-to-file key collision when multiple changed files
  share the same qualified name and line number

### Changed
- Incremental rebuild now parses only changed files instead of all files
- Filesystem scan merged into a single `os.walk` pass instead of two
- Redundant file hash computation eliminated in both full and incremental paths

### Added
- `component_members` table in SQLite schema for future incremental
  connectivity analysis

## [0.1.8] - 2026-07-07

### Added
- Agent prompt auto-update: `install` now scans all installed prompts on start,
  replaces outdated content when its version is below the library version,
  and prints the list of updated agents
- `install` / `uninstall` interactive selection: support Ctrl+C to abort and
  empty input to cancel; prompt texts are now i18n-localized
- `graphlint prompt` subcommand to copy the agent prompt to the system clipboard
- Documentation for agent integration (`docs/*/guide/agent-integration.md`)

### Fixed
- Query deadlock: `_build_edge_mapping` now avoids `result` future list
  mutation under concurrent executor shutdown, preventing infinite waits

## [0.1.7] - 2026-07-06

### Fixed
- `_resolve_symbol` scope filtering no longer drops cross-class `call` edges
  when a method resolves a same-named call via a different class (registry
  / dispatch pattern) — all suffix-matched candidates are now included
- Entry point `file_pattern` matching (`**/*.py` via fnmatch) now also
  matches root-level Python files, not only files in subdirectories

## [0.1.6] - 2026-07-05

### Changed
- `ThreadPoolExecutor` replaced with `ProcessPoolExecutor` for edge building
- Incremental builds on file change now trigger a full rebuild instead of loading prebuilt edges
- Module-level usage expansion in connected-component analysis uses a Counter to distinguish real references from synthetic edges
- Dead-code merge loop uses O(1) `comp_by_id` dict lookup instead of O(C) linear scan

### Removed
- `_quick_changed_check()` — mtime-based fast-path stamp was unreliable on Windows NTFS and could trigger unnecessary incremental builds that produced stale edges
- Ghost-node insertion workaround and stale-edge skip logic in `_do_insert_edges`

## [0.1.5] - 2026-07-05

### Added
- `global` keyword support: `visit_Global` handler tracks names declared as `global X` and resolves references to module-level qualified names (`module.X`) instead of local ones, preventing false local node creation
- `visit_AugAssign` handler for augmented assignment (`X += 1`, `X *= 2`, etc.), generating both read and write references to the target
- Scope isolation for `global` declarations — `_global_names` is saved/restored on function entry/exit, preventing leakage between functions

### Fixed
- `global X` in functions/methods no longer creates spurious local variable nodes for globally-declared names
- Augmented assignment (`X += 1`) was silently dropped during AST traversal — now correctly produces both read and write edges

## [0.1.4] - 2026-07-04

### Fixed
- Module-level dead code detection: removed synthetic `read` edges from pseudo-node 0 that masked all top-level symbols as "used", enabling detection of genuinely dead module-level functions and variables
- Module-level write references no longer create unresolvable edges — variable definitions are not treated as write operations, preventing silent edge drops
- Module-level read/call references now correctly create edges from pseudo-node 0, fixing a false positive where module-level used variables (e.g., `WARN_TYPE_VALUES` read by `VALID_WARN_TYPES = WARN_TYPE_VALUES`) were flagged as dead code
- Public API dunders (`__all__`, `__version__`, etc.) no longer appear as isolated components — they stay anchored to their file via synthetic containment edges
- Python special methods (`__init__`, `__enter__`, `__exit__`, etc.) no longer generate redundant dead-code warnings when their parent class is already flagged as unreachable
- Unreachable classes with special method overloads now produce only the class-level `dead_code` warning, not per-method duplicates

## [0.1.3] - 2026-07-04

### Added
- I18n support for CLI parameter help text: `PARAM_DEFS` help strings now go through the i18n system via `help_key`, enabling full language switching for `--help` output

### Changed
- `ParamDef` dataclass: added `help_key` field for i18n key lookup
- `cli.py:_add_arg()` now resolves help text via `_t(help_key)` when available
- Updated `en.py` and `zh_CN.py` with all `help.param.*` translation entries

## [0.1.2] - 2026-07-04

### Added
- SQLite composite indexes (`idx_edges_source_type`, `idx_edges_target_type`) to accelerate edge-type filtered lookups
- SQLite single-column index (`idx_warnings_node`) to speed up warnings JOIN queries
- SQLite sorted indexes (`idx_snapshots_warnings`, `idx_snapshots_nodes`) for faster list_graphs pagination
- PRAGMA optimizations on Database init: `cache_size=-8000` (8 MB), `mmap_size=268435456` (256 MB), `temp_store=MEMORY`
- `_quick_changed_check()` — mtime-based fast-path stamp that short-circuits the entire build when no files have changed
- `_update_scan_stamp()` — persists `{path: mtime_ns}` snapshot inside IndexLock after each successful build
- `warnings_summary` cache in `QueryEngine.list_graphs()` — lazily computed then shallow-copied, eliminating repeated `GROUP BY` scans
- `_precompute_edge_counts()` — single-pass edge count per component, replacing O(n × m) per-component iteration

### Changed
- Eliminated second AST traversal: edge building is now driven by `ReferenceInfo` collected during the single `ASTVisitor` pass — removed `_walk`, `_read_edges`, `_proc_call`, `_proc_assign`, `_proc_annassign`, `_target_ids`, `_read_target_expr` (~400 lines). In a large codebase (700+ `.py` files, 1000+ classes, 14,000+ functions), full rebuild time improved from ~2500s to ~200s.
- `_build_file_edges_worker` now consumes `ParseResult.references` directly instead of re-walking the AST tree
- Module pseudo-node (id=0) connectivity tightened: liveness only propagates through `read`/`call` edges, not `write` edges — preventing false reachability of write-only variables and fixing false dead-code reports for module-level used variables
- Connected component BFS no longer unconditionally seeds node 0, avoiding spurious reachability
- Module-level synthetic edges recreated for all files each build instead of only for unchanged files
- Optimized multiple AST I/O bottlenecks in source file reading and tree reuse
- `_symbol_index` / `_suffix_index` from `dict` to `defaultdict(list)`, removing all `.setdefault()` calls
- `_resolve_symbol` now accepts a per-worker `resolve_cache` dict — repeated `(qname, scope)` pairs are resolved once per file
- `call_graph` prebuilt once in `find_connected_components` and reused across `compute_entry_reachability` calls, eliminating redundant edge re-traversal
- `_insert_nodes` uses a pre-built `(qualified_name, line_start) → file_path` map instead of O(n²) linear scan via `_node_path()`
- Full rebuild (`incremental=False`) now uses per-table `DELETE FROM` instead of per-file `_delete_old` + selective cleanup
- Incremental build edge insertion now uses global `DELETE FROM edges` instead of per-file partial delete, eliminating dangling old node-ID references
- `load_prebuilt_edges` accepts optional `sql_to_mem` mapping, simplifying caller in `indexer.py`
- Agent injection prompt strengthened to warn when graphlint CLI is unavailable

### Removed
- `_node_path()` helper function (replaced by pre-built node-to-file map)

### Fixed
- Windows compatibility: `os.unlink()` with `missing_ok=True` replaced by `if exists()` guard

## [0.1.1] - 2026-07-04

### Added
- Parallel edge building via ThreadPoolExecutor for changed files (`performance.parallel_workers`)
- Multi-level suffix index for improved symbol resolution beyond single-level short names
- Auto-build retry with full index rebuild on FOREIGN KEY constraint failure

### Changed
- Agent injection prompt wording strengthened to "Always use" with fallback instruction when CLI is unavailable
- Entry detection methods now reuse pre-parsed source (`pr.source`) to reduce redundant file I/O
- Refactored AST walk functions to module level to enable parallel execution

### Fixed
- FOREIGN KEY constraint violations in incremental mode by sorting nodes parent-first before DB insert
- Incremental rebuild no longer rebuilds edges for unchanged files

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
