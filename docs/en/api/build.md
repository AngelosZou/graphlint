# API Reference: build()

`graphlint.api.build()` builds or rebuilds the dependency graph index.

## Signature

```python
def build(
    force_rebuild: bool = False,
    parallel: int = 0,
    root_dir: str = ".",
    lang: str = "system",
) -> dict
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `force_rebuild` | `bool` | `False` | Force full rebuild (ignore SHA256 incremental cache) |
| `parallel` | `int` | `0` | Parallel workers (0=auto-detect CPU cores, max 64) |
| `root_dir` | `str` | `"."` | Project root directory path |
| `lang` | `str` | `"system"` | Interface language: `"system"` / `"zh_CN"` / `"en"` |

## Return Value

Returns a dict with build statistics:

```python
{
    "status": "ok",              # "ok" for success
    "files_scanned": 150,        # Total files scanned
    "files_changed": 12,         # Files with content changes
    "files_added": 3,            # Newly added files
    "files_removed": 1,          # Deleted files
    "nodes_added": 45,           # New AST nodes
    "edges_updated": 120,        # Updated/new edges
    "duration_ms": 320,          # Build duration in milliseconds
    "warnings_generated": 8,     # Warnings generated
}
```

## Incremental Indexing

`build()` uses incremental indexing by default, with the following flow:

1. **Scan files**: Traverse the project directory, collect all `.py` files
2. **Compute hash**: Calculate SHA256 hash for each file
3. **Compare cache**: Compare against hashes in `.graphlint/` cache
4. **Parse only changes**: Only AST-parse files whose hash changed
5. **Update graph**: Merge new and old data, update the dependency graph
6. **Collect warnings**: Detect circular references, unused imports, etc.

When `force_rebuild=True`, steps 2-4 are skipped, performing a full rebuild.

## Parallel Build

The `parallel` parameter controls build parallelism:

- `0` (default): Auto-detect CPU core count
- `N > 0`: Use N workers
- Maximum limit: 64

Parallel builds are implemented via `concurrent.futures.ProcessPoolExecutor`, with each worker independently parsing files.

## Examples

```python
from graphlint.api import build

# Incremental build
result = build()
print(f"Scanned {result['files_scanned']} files, added {result['nodes_added']} nodes")

# Force full rebuild
result = build(force_rebuild=True)
print(f"Duration: {result['duration_ms']}ms")

# Parallel build
result = build(parallel=4)

# Specify project directory
result = build(root_dir="/path/to/project")

# Auto-detect CPU cores parallel build
result = build(parallel=0)
```

## Exceptions

| Exception | Trigger Condition |
|-----------|-------------------|
| `InvalidParamError` | `parallel` parameter is less than 0 |
| `InvalidPathError` | Specified `root_dir` does not exist |
