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
