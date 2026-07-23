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
    {"name": "pytest_test",      "ast_pattern": "test_file",                         "file_pattern": "**/*.py",         "enabled": true, "no_propagate": true},
    {"name": "rust_main",        "ast_pattern": "function_def:main",                 "file_pattern": "**/*.rs",         "enabled": true},
    {"name": "rust_async_main",  "ast_pattern": "decorator:tokio::main | decorator:actix_rt::main | decorator:actix_web::main | decorator:async_std::main | decorator:rocket::main | decorator:rocket::launch | decorator:main", "file_pattern": "**/*.rs", "enabled": true},
    {"name": "rust_wasm_entry",  "ast_pattern": "decorator:wasm_bindgen",            "file_pattern": "**/*.rs",         "enabled": true},
    {"name": "rust_proc_macro",  "ast_pattern": "decorator:proc_macro | decorator:proc_macro_derive | decorator:proc_macro_attribute", "file_pattern": "**/*.rs", "enabled": true},
    {"name": "rust_ffi_export",  "ast_pattern": "decorator:no_mangle | decorator:export_name", "file_pattern": "**/*.rs", "enabled": true},
    {"name": "rust_test",        "ast_pattern": "test_file",                         "file_pattern": "**/*.rs",         "enabled": true, "no_propagate": true},
    {"name": "rust_pub_api",     "ast_pattern": "visibility:pub",                    "file_pattern": "**/*.rs",         "enabled": false}
  ],
  "exclude_patterns": {
    "always_exclude": ["__pycache__/", ".mypy_cache/", ".pytest_cache/", ".tox/", ".venv/", "venv/", "env/", "virtualenv/", ".env/", "node_modules/", ".git/", ".svn/", ".hg/", ".idea/", ".vscode/", ".vs/", ".graphlint/", "build/", "dist/", "target/", ".cargo/", "*.egg-info/", "*.pyc", "*.pyo"],
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
    "file_patterns": ["test_*.py", "*_test.py", "test_*.rs", "*_test.rs"],
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

**Note:** The `rust_pub_api` rule (pattern `visibility:pub`, Rust only) is **disabled by default** (`"enabled": false`). Use `--public-as-entry` at query time, or manually set `"enabled": true` in the config for persistent library-crate analysis.

### --public-as-entry Flag

The `--public-as-entry` CLI flag (or `public_as_entry=True` API parameter) treats all public items as execution entry points:

```bash
graphlint query --public-as-entry
```

- **Scope:** Only affects languages with `public` visibility declarations (Rust `pub`). Has no effect on Python files.
- **Re-indexing:** Toggling the flag triggers a full rebuild (the flag value is stored in the scan stamp). For long-term use, prefer enabling the `rust_pub_api` config rule or adding custom `visibility:pub` entry rules to avoid repeated rebuilds.
- **Config interaction:** Independent of the `rust_pub_api` config rule — the two mechanisms are orthogonal and do not interfere.

#### AST Pattern Prefixes

All rules use the same prefix pattern syntax, supporting OR combinations with ` | `:

| Prefix | Match Target | Example | Languages |
|--------|-------------|---------|-----------|
| `function_call:` | Function call | `"function_call:my_entry"` | Python |
| `function_def:` | Function definition name (supports glob) | `"function_def:run_*"` | Python, Rust |
| `decorator:` | Decorator or attribute macro (`#[...]`) | `"decorator:app.route"` / `"decorator:tokio::main"` | Python, Rust |
| `class_instantiation:` | Class instantiation | `"class_instantiation:MyApp"` | Python |
| `file_match:` | Filename match | `"file_match:**/main.py"` | Python, Rust |
| `if_name_main` | `if __name__ == '__main__'` check | `"if_name_main"` | Python |
| `test_file` | Test file detection (uses `test_patterns` config) | `"test_file"` | Python, Rust |
| `visibility:pub` | Items with `pub` visibility modifier | `"visibility:pub"` | Rust |
| `trait_impl:` | Trait implementation block | `"trait_impl:Default"` | Rust |
| `macro_def:` | `macro_rules!` definition | `"macro_def:my_macro"` | Rust |

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
