---
name: graphlint
description: Load for codebase understanding, exploration, and modification — maps the real dependency graph to separate live, reachable code from dead code and unused imports, so refactors, cleanups, and deletions are safe.
---

# graphlint — Dead-Code & Dependency Analysis

Static analysis of a project's dependency graph: finds components unreachable from any entry point (dead code), plus unused imports and other warnings.

**Languages:** Python (built in) · Rust (`pip install graphlint[rust]`) · C# (`pip install graphlint[csharp]`) · C/C++ (`pip install graphlint[c]`) · TypeScript/JavaScript (`pip install graphlint[typescript]`) · GDScript/Godot (`pip install graphlint[godot]`)

## When to use
- When understanding or exploring a codebase: see how a feature is wired in and which code is actually reachable.
- Before modifying, refactoring, or deleting code: confirm a symbol is truly live before you change or remove it.
- After modifications: verify your edits left no dead or redundant code behind.

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
- `-w, --warn-types <list>` — filter, e.g. `dead_code,unused_import,write_only`
- `-C, --exclude-clean` — only graphs with issues
- `-R, --reachability` — only graphs reachable from entry points
- `--public-as-entry` — treat public items (Rust `pub`, C# `public`, C external-linkage symbols) as entry points (library analysis)
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
graphlint query --fail-on dead_code,unused_import # CI gate
```

## Limitations
- **Static analysis only** — dynamic references (`getattr`, `importlib`, reflection, DI containers) can yield false positives. Verify before deleting and add custom entry rules (above) for your conventions.
- **C/C++ family** — a single unified C/C++ analyzer owns `.c/.h/.cpp/.cc/.cxx/.hpp/.hh/.hxx`. `.c` uses `tree-sitter-c`, the C++ suffixes use `tree-sitter-cpp`, and a `.h` is routed by the language of the TU(s) that include it (never by content-sniffing). The preprocessor is pure AST (`#if` is never evaluated, macros are not expanded); function-pointer call targets are not traced; member calls resolve type-aware across translation units, but there is **no dynamic dispatch / virtual / template instantiation**. A C++-defined class with **no `main`** and only headers needs custom entry rules (`file_match:**/*.h`); C projects enter library mode automatically (`c_library_mode`, default `auto`) — external-linkage symbols become entries.
- **GDScript / Godot** — one adapter owns `.gd` + `.tscn` + `.tres` + `project.godot` (Godot 4.x): scene→script attachment, `preload`/`load`/`class_name`, the main scene, autoloads and editor-wired `[connection]` handlers are all in the graph, and whole-project checks flag missing `res://` paths (the engine only warns and exits 0). String dispatch, computed `load`/`get_node`/`Expression` and GDExtension are unprovable: literal dispatch names and `.tscn` handlers act as entries, an unprovable script keeps all its members alive, and per-method/signal/constant verdicts stay opt-in (`godot.method_dead_code`, …). Defaults give file/asset-level verdicts; `class_name` is a public API entry unless `godot.public_class_api: false`.
- **Build cost** — a full rebuild of a large codebase (~700 files) takes ~200 s; small projects (~60 files) take ~1 s. Regular `query` runs are incremental and cheap — avoid `build --force` mid-refactoring.
