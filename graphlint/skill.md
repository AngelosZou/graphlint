---
name: graphlint
description: Dead-code detection for AI-generated codebases via the graphlint dependency-graph analyzer.
---

# graphlint — Dead-Code & Dependency Analysis

Static analysis of a project's dependency graph: finds components unreachable from any entry point (dead code), plus circular references, unused imports and other warnings.

**Languages:** Python (built in) · Rust (`pip install graphlint[rust]`) · C# (`pip install graphlint[csharp]`)

## When to use
- After code modifications: check whether your edits left dead or redundant code.
- Before analyzing or changing a codebase: understand how a feature is wired in.

## Core commands
```bash
graphlint query                  # List dependency graphs; auto-rebuilds the index incrementally
graphlint query --json           # Structured output
graphlint query -g <id> -d full  # Full detail on one graph
graphlint config show            # Current project config
```

Run `query` normally — it keeps the index up to date by itself (automatic incremental build). Use `graphlint build --force` **only when query results look wrong or stale**; a full rebuild is slow on large codebases.

## Key parameters
- `-g, --graph-id <id>` — detail on one graph
- `-j, --json` — structured output
- `-w, --warn-types <list>` — filter, e.g. `dead_code,circular_ref,unused_import`
- `-C, --exclude-clean` — only graphs with issues
- `-R, --reachability` — only graphs reachable from entry points
- `--public-as-entry` — treat public items (Rust `pub`, C# `public`) as entry points (library analysis)
- `-t, --include-tests` — include test files
- `--dead-code-tests` — find tests that reference suspected dead code
- `--sort-by <warnings|nodes|edges|name>` · `--min-nodes N` · `--max-nodes N` · `-n, --max-results N`
- `-r, --root-dir <path>` — project root (default `.`)
- `--fail-on <types>` — exit non-zero when matching warnings exist (CI gates)
- build: `-f, --force` · `-P, --parallel N`

`graphlint query -h` lists everything.

## Custom entry rules
Dead-code results depend on correct entry points. If graphlint flags code your framework invokes dynamically (routers, plugins, DI containers, `getattr`/`importlib`), add entry rules matching your project's conventions instead of deleting that code:

```bash
graphlint config add-entry-rule --rule-json '{"name":"my_service","ast_pattern":"class_instantiation:FastAPI","file_pattern":"**/service.py"}'
graphlint config remove-entry-rule --name my_service
graphlint config add-exclude --exclude-pattern "*/generated/*"
```

## Examples
```bash
graphlint query -C --json                        # Any issues after a refactor?
graphlint query -w dead_code --sort-by warnings  # Dead code by severity
graphlint query -g 5 -d full                     # Inspect one component
graphlint query --fail-on dead_code,circular_ref # CI gate
```

## Limitations
- **Static analysis only** — dynamic references (`getattr`, `importlib`, reflection, DI containers) can yield false positives. Verify before deleting and add custom entry rules (above) for your conventions.
- **Build cost** — a full rebuild of a large codebase (~700 files) takes ~200 s; small projects (~60 files) take ~1 s. Regular `query` runs are incremental and cheap — avoid `build --force` mid-refactoring.
