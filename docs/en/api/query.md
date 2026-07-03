# API Reference: query()

`graphlint.api.query()` queries the code dependency graph.

## Signature

```python
def query(
    include_tests: bool = False,
    exclude_clean: bool = False,
    exclude_unreachable: bool = False,
    dead_code_tests: bool = False,
    graph_id: Optional[int] = None,
    json_output: bool = False,
    path_format: str = "relative",
    root_dir: str = ".",
    max_results: int = 50,
    min_nodes: int = 0,
    max_nodes: Optional[int] = None,
    warn_types: Optional[str] = None,
    sort_by: str = "warnings",
    detail_level: str = "auto",
    output_limit: int = 8000,
    edge_limit: int = 10,
    file_limit: int = 10,
    node_limit: int = 30,
    no_scan: bool = False,
    lang: str = "system",
) -> Union[str, dict]
```

## Parameters

### Filter Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_tests` | `bool` | `False` | Include nodes from test files |
| `exclude_clean` | `bool` | `False` | Show only graphs with warnings/errors |
| `exclude_unreachable` | `bool` | `False` | Return only graphs reachable from entry points via CALL edges |
| `dead_code_tests` | `bool` | `False` | Query tests that reference dead code |
| `graph_id` | `Optional[int]` | `None` | Query detail for a specific graph |
| `min_nodes` | `int` | `0` | Only return graphs with ≥ N nodes |
| `max_nodes` | `Optional[int]` | `None` | Only return graphs with ≤ N nodes |
| `warn_types` | `Optional[str]` | `None` | Comma-separated warning type filter |

### Output Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `json_output` | `bool` | `False` | Structured JSON output |
| `path_format` | `str` | `"relative"` | Path format: `"absolute"` / `"relative"` |
| `max_results` | `int` | `50` | Max graphs returned (1–1000) |
| `sort_by` | `str` | `"warnings"` | Sort by: `"warnings"` / `"nodes"` / `"edges"` / `"name"` |
| `detail_level` | `str` | `"auto"` | Detail level: `"auto"` / `"summary"` / `"full"` / `"minimal"` |
| `output_limit` | `int` | `8000` | Output text length limit (chars, 100–100000) |
| `edge_limit` | `int` | `10` | Max edges in graph detail (0=unlimited) |
| `file_limit` | `int` | `10` | Max files in graph detail (0=unlimited) |
| `node_limit` | `int` | `30` | Max nodes in graph detail (0=unlimited) |

### Behavior Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `root_dir` | `str` | `"."` | Target project root directory |
| `no_scan` | `bool` | `False` | Skip auto-scan/build, query existing index only |
| `lang` | `str` | `"system"` | Interface language: `"system"` / `"zh_CN"` / `"en"` |

## Return Value

### Text Mode (`json_output=False`, default)

Returns a formatted string containing graph list or detail.

### JSON Mode (`json_output=True`)

Returns a dict with the following structure:

```json
{
  "status": "ok",
  "query_time_ms": 150,
  "total_graphs": 5,
  "returned": 5,
  "root_dir": "/path/to/project",
  "graphs": [
    {
      "graph_id": 1,
      "name": "module_name",
      "nodes_count": 12,
      "edges_count": 25,
      "entry_count": 2,
      "warnings": 3,
      "warnings_detail": [
        {"type": "circular_ref", "severity": "warning", "message": "...", "file": "..."}
      ]
    }
  ]
}
```

When querying detail (with `graph_id`):

```json
{
  "status": "ok",
  "query_time_ms": 25,
  "graph_id": 1,
  "name": "module_name",
  "nodes": [
    {"id": 1, "name": "MyClass", "type": "class", "line": 10, "file": "src/module.py"}
  ],
  "edges": [
    {"source": 1, "target": 2, "type": "call", "line": 15}
  ],
  "warnings": [...]
}
```

## Examples

```python
from graphlint.api import query

# Basic query
result = query()

# JSON output, sorted by warning count
result = query(
    include_tests=True,
    json_output=True,
    max_results=20,
    sort_by="warnings",
)

# Query specific graph detail
detail = query(graph_id=1, detail_level="full", json_output=True)

# Query dead code test references
dead = query(dead_code_tests=True, json_output=True)

# Query only circular reference warnings
circ = query(warn_types="circular_ref", json_output=True)

# Minimal output
minimal = query(detail_level="minimal", max_results=5)
```

## Exceptions

| Exception | Trigger Condition |
|-----------|-------------------|
| `InvalidParamError` | Parameter value outside valid range |
| `InvalidPathError` | Specified `root_dir` does not exist |
| `NoIndexError` | No built index and `no_scan=True` |
| `InvalidGraphIdError` | Specified `graph_id` does not exist |
| `HashMismatchError` | File hash changed, cache invalidated |
