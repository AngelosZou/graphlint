# Architecture Overview

graphlint is positioned as a dead code detection tool for AI-generated codebases (Python, Rust, and more in the future). It analyzes the dependency graph to find components unreachable from all entry points (dead code), helping agents clean redundant code and reduce context pollution and attention dilution.

## Overall Architecture

graphlint uses a layered modular architecture with clear responsibilities and dependency direction from top to bottom.

```
┌──────────────────────────────────────────────────┐
│                  API Layer                          │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ query()  │  │ build()  │  │ configure()   │   │
│  └────┬─────┘  └────┬─────┘  └───────┬───────┘   │
├───────┴─────────────┴─────────────────┴──────────┤
│                  CLI Layer                          │
│  ┌─────────────────────────────────────────────┐  │
│  │  graphlint query / build / config           │  │
│  └─────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────┤
│               Business Logic Layer                  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ Query    │  │Incremen- │  │ ConfigManager │   │
│  │ Engine   │  │talIndexer│  │               │   │
│  └────┬─────┘  └────┬─────┘  └───────┬───────┘   │
├───────┴─────────────┴─────────────────┴──────────┤
│               Analysis Engine Layer                 │
│  ┌─────────┐ ┌────────┐ ┌─────────┐ ┌─────────┐ │
│  │Language │ │Graph   │ │EntryPt  │ │Warning  │ │
│  │Registry │ │Builder │ │Detector │ │Collector│ │
│  └────┬────┘ └───┬────┘ └────┬────┘ └────┬────┘ │
│       │          │            │            │      │
│  ┌────┴─────────┐ ┌───┴────┐      │       │      │
│  │Language      │ │ Graph  │      │       │      │
│  │Adapter (multi)│ │ Algo   │      │       │      │
│  └──────────────┘ └────────┘      │       │      │
├────────────────────────────────────────────┴─────┤
│               Storage / Persistence Layer           │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ Database │  │ Hashing  │  │ Schema        │   │
│  └──────────┘  └──────────┘  └───────────────┘   │
├───────────────────────────────────────────────────┤
│               Infrastructure Layer                  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ I18n     │  │ Params   │  │ Exceptions    │   │
│  │ Manager  │  │ Defs     │  │               │   │
│  └──────────┘  └──────────┘  └───────────────┘   │
└───────────────────────────────────────────────────┘
```

## Key Data Structures

### Reachability Cache (`.graphlint/.reachability_cache`)

A JSON file caching the `reachable` and `expanded` node-ID sets from the
last successful build. On the next incremental build, instead of running a
full O(N+E) connected-component BFS, graphlint loads this cache and applies
a delta-aware algorithm that only propagates from changed and newly-entered
nodes.

- `reachable` — all node IDs reachable from any entry point
- `expanded` — node IDs whose CALL-graph downstream was fully explored
  (excludes test-only nodes that don't propagate reachability)

## Module Responsibilities

### 1. API Layer (`graphlint/api.py`)

Provides three top-level functions as the public interface:

- **`query()`** — Query the dependency graph, supports list/detail modes, text/JSON output, and multiple filters
- **`build()`** — Build or rebuild the dependency graph index, supports incremental mode and parallel processing
- **`configure()`** — Manage configuration, supports show/get/set/copy-from, entry rules, and exclude pattern management

### 2. CLI Layer (`graphlint/cli.py`)

Command-line interface built on `argparse`:

- Three subcommands: `query`, `build`, `config`
- Parameter definitions shared with `params.py`, ensuring CLI and API parameter consistency
- Supports nested subcommands (e.g., `config show`, `config set`)

### 3. Business Logic Layer

- **`QueryEngine`** (`graphlint/query/engine.py`) — Encapsulates SQLite query logic, handles graph listing, details, hash validation, dead code test queries
- **`IncrementalIndexer`** (`graphlint/incremental/indexer.py`) — Manages incremental build workflow, uses SHA256 hashing to detect file changes
- **`ConfigManager`** (`graphlint/config/manager.py`) — Configuration loading, saving, reading, copying
- **`VolumeStrategy`** (`graphlint/query/volume.py`) — Adaptive output volume strategy (full/summary/truncated)
- **`TextFormatter`** (`graphlint/query/formatter.py`) — Text formatting output

### 4. Analysis Engine Layer

- **`LanguageRegistry`** (`graphlint/analyzer/language/registry.py`) — Language adapter registry, routes files to backends by extension, laying the foundation for future multi-language support
- **`LanguageAdapter`** (`graphlint/analyzer/language/base.py`) — Abstract base class for language backends, defining unified interfaces for parsing, entry detection, node matching, etc.; the current Python implementation lives in `language/python/`
- **`SourceParser`** (`graphlint/analyzer/language/python/parser.py`) — Recursively scans directories, performs AST parsing on each `.py` file
- **`GraphBuilder`** (`graphlint/analyzer/graph.py`) — Builds the dependency graph from parse results, including nodes, edges, and connected component analysis. Edges are built in parallel per file from structured `ReferenceInfo` collected during AST parsing — no second AST walk is needed.
- **`EntryPointDetector`** (`graphlint/analyzer/language/python/entry.py`) — 10 built-in entry detection rules + custom rule support
- **`WarningCollector`** (`graphlint/analyzer/warnings.py`) — Warning collection, deduplication, filtering, and statistics
- **`ImportAnalyzer`** (`graphlint/analyzer/language/python/imports.py`) — Import statement parsing and unused import detection

#### AST Parsing & Edge Building Flow

```
Source File (.py, etc.)
    │
    ▼
LanguageRegistry route → LanguageAdapter dispatch
    │
    ▼
AST Parse (ast.parse / other language parser)
    │
    ▼
ASTVisitor Traversal (single pass)
    ├── Extract nodes (classes/functions/methods/structs/enums/traits/impls/variables/fields)
    ├── Parse import statements (Python) / use declarations (Rust)
    ├── Collect name usage
    └── Collect structured references (ReferenceInfo — read/write/call/inherit/decorate)
    │
    ▼
GraphBuilder Build Graph
    ├── Add nodes (assign IDs)
    ├── Add edges from ReferenceInfo — no second AST walk
    ├── Entry point detection
    ├── Connected component analysis (call graph prebuilt once and reused across reachability computations)
    └── Warning collection
```

### 5. Storage / Persistence Layer

- **`Database`** (`graphlint/storage/db.py`) — SQLite database wrapper with transaction support
- **`Hashing`** (`graphlint/storage/hashing.py`) — File SHA256 hash computation
- **`Schema`** (`graphlint/storage/schema.py`) — Database table structure definitions

#### Database Table Structure

| Table | Description |
|-------|-------------|
| `files` | File metadata (path, hash, size) |
| `nodes` | AST nodes (name, type, location, file association) |
| `edges` | Dependency edges (source/target node, edge type, location) |
| `imports` | Import records (module path, import name, usage status) |
| `warnings` | Warning information |
| `graph_snapshots` | Graph structure snapshots (node/edge/warning counts, reachability markers) |

### 6. Infrastructure Layer

- **`I18nManager`** (`graphlint/i18n/__init__.py`) — Internationalization support, provides `zh_CN` and `en` languages
- **`ParamDef`** (`graphlint/params.py`) — Unified parameter definitions, CLI and API share the same parameter source
- **`Exceptions`** (`graphlint/exceptions.py`) — Custom exception hierarchy

## Data Flow

### Query Flow

```
query() call
    │
    ▼
Check if index exists? ──no──→ Auto execute build()
    │ yes
    ▼
Open SQLite database
    │
    ├── graph_id specified? ──→ Query details → Format output
    │
    └── List mode
        │
        ▼
    Apply filters (warn_types, min_nodes, include_tests...)
        │
        ▼
    Sort (warnings/nodes/edges/name)
        │
        ▼
    Output volume strategy decision (auto/summary/full/minimal)
        │
        ▼
    Text formatting or JSON serialization
```

### Build Flow

```
build() call
    │
    ▼
Scan directory, collect .py files
    │
    ├── Incremental mode? ──→ Compute SHA256 → Compare with cache → Process only changed files
    │
    └── Force rebuild? ──→ Process all files
    │
    ▼
AST parsing (parallel)
    │
    ▼
GraphBuilder builds graph
    │
    ▼
Entry point detection
    │
    ▼
Connected component analysis (call graph prebuilt once)
    │
    ▼
Warning collection and deduplication
    │
    ▼
Write to SQLite database
    │
    ▼
Return statistics
```

### Incremental Rebuild Mechanism

When files change, graphlint avoids re-parsing the entire codebase. Instead, it performs a targeted incremental rebuild in six phases:

```
┌─────────────────────────────────────────────────────────────┐
│  Phase 1: Remove                                            │
│  Delete all data for changed+removed files from DB          │
│  (nodes, edges, imports — both internal and cross-file)     │
├─────────────────────────────────────────────────────────────┤
│  Phase 2: Parse                                             │
│  Re-parse changed files via AST; load unchanged files from  │
│  the DB cache (hashed via SHA256)                            │
├─────────────────────────────────────────────────────────────┤
│  Phase 3: Downstream Reconnect                              │
│  Restore edges from unchanged files → changed files.        │
│  These "prebuilt" edges were recorded in the DB before the  │
│  changed files' old data was removed. Each edge is re-      │
│  validated against the new node IDs in the rebuilt graph.   │
│  Edges referencing removed-file symbols are filtered out.   │
├─────────────────────────────────────────────────────────────┤
│  Phase 4: Rebuild                                           │
│  GraphBuilder reconstructs:                                 │
│    • Upstream edges — within changed files + changed →      │
│      unchanged + changed → external (these may differ from  │
│      the original connections)                              │
│    • Downstream remapping — prebuilt edges from Phase 3     │
│      are remapped to new node IDs                           │
│    • Component analysis — delta-aware reachability          │
│      propagation (see below)                                │
├─────────────────────────────────────────────────────────────┤
│  Phase 5: Persist                                           │
│  Write updated nodes and only changed-file edges to SQLite  │
│  (unchanged edges are retained in place). Fix parent_node_id│
│  remappings and remap downstream edge references via        │
│  targeted SQL UPDATE statements.                            │
├─────────────────────────────────────────────────────────────┤
│  Phase 6: Verify                                            │
│  Lightweight integrity check: LEFT JOIN queries detect      │
│  dangling edge references without loading all edges into    │
│  memory.                                                    │
└─────────────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **Upstream vs. downstream**: Upstream edges (changed → others) are rebuilt from scratch by `GraphBuilder` because the changed code may have added, removed, or altered its references. Downstream edges (others → changed) are restored from precomputed records because unchanged code's references are stable — we only need to remap node IDs.

- **Delta-aware reachability**: Instead of a full O(N+E) BFS from entry points on every incremental build, the algorithm loads the old `(reachable, expanded)` cache and only propagates changes from affected nodes:

  1. **Forward propagation** — entry nodes that are new or changed, plus changed nodes that were previously reachable, are seeded into a BFS queue. Their CALL-graph targets are explored and added to the reachable set.
  2. **Loss propagation** — changed nodes that were previously reachable but now have no reachable caller are removed from the reachable set. The algorithm walks downstream, pruning nodes whose only reachable caller was just removed.
  3. **Multi-source pruning** — a reverse CALL graph allows checking whether a potentially-pruned node has *any other* reachable caller. If another reachable caller exists, the node is retained and loss propagation stops there.

  This reduces the incremental reachability cost from O(N+E) to O(|C| + |Δ|), where C is the changed-node set and Δ is the set of nodes whose reachability actually changed.

- **Edge persistence**: In incremental mode, only edges built from changed files are inserted. Unchanged downstream edge references are remapped via targeted SQL `UPDATE` statements when node IDs change.

- **Caching strategy**: Unchanged files are not re-parsed. Their nodes, edges, and metadata are loaded directly from the SQLite database, validated by SHA256 hash comparison. The reachability cache (`.graphlint/.reachability_cache`) persists the reachable/expanded sets across builds so the incremental algorithm can start from a known-good state. This keeps the incremental rebuild cost proportional to the number of changed files, not the total codebase size.
