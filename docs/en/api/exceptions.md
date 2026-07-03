# Exception Reference

Custom exception hierarchy defined by graphlint.

## Exception Hierarchy

```
Exception
  └── GraphlintError (base class)
        ├── ConfigNotFoundError
        ├── InvalidPathError
        ├── HashMismatchError
        ├── NoIndexError
        ├── InvalidGraphIdError
        └── InvalidParamError
```

## Exception Details

### GraphlintError

Base class for all graphlint exceptions.

```python
class GraphlintError(Exception):
    def __init__(self, message: str = "") -> None
```

### ConfigNotFoundError

Raised when the configuration file is missing.

```python
class ConfigNotFoundError(GraphlintError):
    def __init__(self, path: str = "") -> None
```

**Triggered when**: `.graphlint/config.json` does not exist and the default configuration cannot be created.

### InvalidPathError

Raised when path validation fails.

```python
class InvalidPathError(GraphlintError):
    def __init__(self, path: str = "", reason: str = "") -> None
```

**Triggered when**: Specified `root_dir` does not exist.

### HashMismatchError

Raised when file hashes do not match.

```python
class HashMismatchError(GraphlintError):
    def __init__(self, file_path: str = "", old_hash: str = "", new_hash: str = "") -> None
```

**Triggered when**: A file's SHA256 hash differs from the cache during query, indicating external modification.

### NoIndexError

Raised when the index does not exist.

```python
class NoIndexError(GraphlintError):
    def __init__(self, root_dir: str = "") -> None
```

**Triggered when**: Querying with `no_scan=True` and `.graphlint/db.sqlite` does not exist.

### InvalidGraphIdError

Raised when an invalid graph ID is specified.

```python
class InvalidGraphIdError(GraphlintError):
    def __init__(self, graph_id: int = 0, max_id: int = 0) -> None
```

**Triggered when**: Specified `graph_id` is out of valid range (1 to max ID).

### InvalidParamError

Raised when a parameter value is invalid.

```python
class InvalidParamError(GraphlintError):
    def __init__(self, param_name: str = "", value: str = "", reason: str = "") -> None
```

**Triggered when**: API parameter values are outside valid range, for example:
- `graph_id` ≤ 0
- `min_nodes` < 0
- `max_results` not in 1–1000 range
- `output_limit` not in 100–100000 range
- `path_format` is not `"absolute"` or `"relative"`
- `sort_by` is not a valid value
- `warn_types` contains an invalid warning type
- `parallel` < 0
