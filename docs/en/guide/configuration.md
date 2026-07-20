# Configuration Guide

graphlint's configuration file is located at `.graphlint/config.json` in the project root directory, using JSON format.

## Default Configuration

```json
{
  "entry_rules": [
    {"name": "python_main",      "ast_pattern": "if_name_main",                      "file_pattern": "**/*.py",         "enabled": true},
    {"name": "python_package",   "ast_pattern": "file_match:**/__init__.py",         "file_pattern": "**/__init__.py",  "enabled": true},
    {"name": "fastapi_app",      "ast_pattern": "class_instantiation:FastAPI | function_call:uvicorn.run", "file_pattern": "**/*.py", "enabled": true},
    {"name": "flask_app",        "ast_pattern": "class_instantiation:Flask | class_instantiation:flask.Flask | function_call:*.run", "file_pattern": "**/*.py", "enabled": true},
    {"name": "django_manage",    "ast_pattern": "function_call:execute_from_command_line", "file_pattern": "**/manage.py", "enabled": true},
    {"name": "click_command",    "ast_pattern": "decorator:click.command | decorator:click.group", "file_pattern": "**/*.py", "enabled": true},
    {"name": "typer_app",        "ast_pattern": "class_instantiation:typer.Typer | decorator:*.command", "file_pattern": "**/*.py", "enabled": true},
    {"name": "celery_app",       "ast_pattern": "class_instantiation:Celery | class_instantiation:celery.Celery", "file_pattern": "**/*.py", "enabled": true},
    {"name": "pytest_plugin",    "ast_pattern": "function_def:pytest_addoption | decorator:pytest.fixture", "file_pattern": "**/conftest.py", "enabled": true},
    {"name": "pytest_test",      "ast_pattern": "test_file",                         "file_pattern": "**/*.py",         "enabled": true, "no_propagate": true}
  ],
  "exclude_patterns": {
    "always_exclude": ["__pycache__/", ".mypy_cache/", ".pytest_cache/", ".tox/", ".venv/", "venv/", "env/", "virtualenv/", ".env/", "node_modules/", ".git/", ".svn/", ".hg/", ".idea/", ".vscode/", ".vs/", ".graphlint/", "build/", "dist/", "*.egg-info/", "*.pyc", "*.pyo"],
    "user_exclude": []
  },
  "lang": "system",
  "output": {
    "default_detail": "auto",
    "default_max_results": 50,
    "default_output_limit": 8000
  },
  "performance": {
    "hash_algorithm": "sha256",
    "max_file_size_mb": 10,
    "parallel_workers": 0
  },
  "test_patterns": {
    "config_files": ["conftest.py"],
    "dir_patterns": ["tests/", "test/", "__tests__/"],
    "file_patterns": ["test_*.py", "*_test.py"],
    "function_patterns": ["test_*"]
  },
  "version": 1
}
```

## Configuration Reference

### entry_rules — Entry Detection Rules

Defines how code entry points are auto-detected. Each rule contains:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `string` | Unique rule name |
| `ast_pattern` | `string` | AST match pattern (unified prefix syntax for all rules) |
| `file_pattern` | `string` | Glob pattern to match filenames |
| `description` | `string` | Rule description (optional) |
| `enabled` | `boolean` | Whether the rule is enabled |
| `no_propagate` | `boolean` | Entry does not propagate reachability (default `false`, e.g. pytest test rules set to `true`) |

#### AST Pattern Prefixes

All rules use the same prefix pattern syntax, supporting OR combinations with ` | `:

| Prefix | Match Target | Example |
|--------|-------------|---------|
| `function_call:` | Function call | `"function_call:my_entry"` |
| `function_def:` | Function definition name (supports glob) | `"function_def:run_*"` |
| `decorator:` | Decorator | `"decorator:app.route"` |
| `class_instantiation:` | Class instantiation | `"class_instantiation:MyApp"` |
| `file_match:` | Filename match | `"file_match:**/main.py"` |
| `if_name_main` | `if __name__ == '__main__'` check | `"if_name_main"` |
| `test_file` | Test file detection (uses `test_patterns` config) | `"test_file"` |

### exclude_patterns — Exclude Patterns

| Field | Type | Description |
|-------|------|-------------|
| `always_exclude` | `string[]` | Always-excluded directories/files (immutable) |
| `user_exclude` | `string[]` | User-defined exclude patterns (manageable via CLI or API) |

### lang — Language Setting

Supported values:
- `"system"` — Follow system language (auto-detect)
- `"zh_CN"` — Simplified Chinese
- `"en"` — English

### output — Output Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_detail` | `string` | `"auto"` | Default detail level: `"auto"` / `"summary"` / `"full"` / `"minimal"` |
| `default_max_results` | `int` | `50` | Default max results returned |
| `default_output_limit` | `int` | `8000` | Text output character limit |

### performance — Performance Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `hash_algorithm` | `string` | `"sha256"` | File content hash algorithm |
| `max_file_size_mb` | `int` | `10` | Files exceeding this size are skipped |
| `parallel_workers` | `int` | `0` | Parallel workers (0=auto) |

### test_patterns — Test File Recognition Patterns

| Field | Type | Description |
|-------|------|-------------|
| `config_files` | `string[]` | Test config file patterns |
| `dir_patterns` | `string[]` | Test directory match patterns |
| `file_patterns` | `string[]` | Test filename match patterns |
| `function_patterns` | `string[]` | Test function match patterns |

## Configuration Management

### Method 1: CLI

```bash
# View configuration
graphlint config show

# Set configuration
graphlint config set --key lang --value en

# Add entry rule
graphlint config add-entry-rule --rule-json '{"name":"my_app","ast_pattern":"function_call:start","file_pattern":"**/app.py"}'

# Add exclude pattern
graphlint config add-exclude --exclude-pattern "generated/"
```

### Method 2: Python API

```python
from graphlint.api import configure

# View configuration
configure(action="show")

# Set configuration
configure(action="set", key="performance.max_file_size_mb", value="20")
```

### Method 3: Direct Editing

Edit `.graphlint/config.json` directly. Changes take effect on the next query or build.

## Configuration Priority

1. Python API call parameters (highest)
2. CLI command-line arguments
3. `.graphlint/config.json` configuration file
4. Built-in defaults (lowest)
