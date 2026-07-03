# Warning Type Reference

graphlint supports 11 code analysis warning types.

## Warning Types Overview

| Warning Type | Severity | Description |
|-------------|----------|-------------|
| `unused_import` | `warning` | Imported module or name is never used |
| `dynamic_import` | `warning` | Dynamic import (e.g., `__import__()` or `importlib.import_module()`) |
| `circular_ref` | `warning` | Circular dependency between modules or components |
| `syntax_error` | `error` | File contains a syntax error, cannot be parsed |
| `write_only` | `warning` | Variable is assigned but never read |
| `deprecated_usage` | `warning` | Usage of a deprecated API |
| `dead_code` | `info` | Code unreachable from any entry point |
| `type_mismatch` | `warning` | Type annotation conflicts with literal value type |
| `unresolved_ref` | `warning` | Reference to an unresolved symbol |
| `unused_variable` | `warning` | Variable is defined but never used |
| `file_too_large` | `info` | File exceeds size limit and was skipped |

## Detailed Reference

### unused_import — Unused Import

Detects unused import statements. The analyzer collects all used names in a file and compares them against imported names.

**Example**:
```python
import os        # If os is not used later in the code → warning
import sys       # If sys is used → OK
```

### dynamic_import — Dynamic Import

Detects dynamic imports using `__import__()` or `importlib.import_module()`. If the module name is dynamically constructed (e.g., f-string or string concatenation), it is flagged as a dynamic import.

**Example**:
```python
module = __import__(f"plugin_{name}")       # Dynamic import → warning
lib = importlib.import_module("json")        # Absolute import → OK
```

### circular_ref — Circular Reference

Detects circular dependencies between components via graph algorithms. Triggered when two or more components have mutual references.

### syntax_error — Syntax Error

Triggered when a file cannot be parsed by `ast.parse()`. Usually indicates Python syntax errors.

### write_only — Write-Only Variable

Variable is assigned but never read. The analyzer checks each variable/field node for READ edges.

**Example**:
```python
x = 10      # Assigned 10
x = 20      # Reassigned, but x was never read → warning
```

### deprecated_usage — Deprecated API

Detects usage of functions or classes marked with the `@deprecated` decorator.

### dead_code — Dead Code

Components (connected components) unreachable from any entry point. Triggered when no node in a connected component is marked as an entry point.

### type_mismatch — Type Mismatch

Type annotation conflicts with the literal value type.

**Example**:
```python
count: int = "hello"    # Annotated as int but assigned a string → warning
```

### unresolved_ref — Unresolved Reference

Reference to a symbol that cannot be found in the symbol index.

### unused_variable — Unused Variable

Variable is defined but never read or written.

**Example**:
```python
def func():
    x = 10      # Defined but never used → warning
    return
```

### file_too_large — File Too Large

File size exceeds the `performance.max_file_size_mb` config value (default 10MB), skipped from AST parsing.

## Filtering Warnings

### CLI Method

```bash
# Show only circular reference warnings
graphlint query --warn-types "circular_ref"

# Show multiple warning types
graphlint query --warn-types "circular_ref,unused_import"
```

### API Method

```python
from graphlint.api import query

# Show only circular references
result = query(warn_types="circular_ref", json_output=True)

# Exclude clean graphs
result = query(exclude_clean=True)
```
