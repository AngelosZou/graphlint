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
    {"name": "rust_default_bin_path", "ast_pattern": "file_match:src/main.rs | file_match:src/bin/*.rs", "file_pattern": "**/*.rs", "enabled": true},
    {"name": "rust_main",        "ast_pattern": "function_def:main",                 "file_pattern": "**/*.rs",         "enabled": true},
    {"name": "rust_async_main",  "ast_pattern": "decorator:tokio::main | decorator:actix_rt::main | decorator:actix_web::main | decorator:async_std::main | decorator:rocket::main | decorator:rocket::launch | decorator:main", "file_pattern": "**/*.rs", "enabled": true},
    {"name": "rust_wasm_entry",  "ast_pattern": "decorator:wasm_bindgen",            "file_pattern": "**/*.rs",         "enabled": true},
    {"name": "rust_proc_macro",  "ast_pattern": "decorator:proc_macro | decorator:proc_macro_derive | decorator:proc_macro_attribute", "file_pattern": "**/*.rs", "enabled": true},
    {"name": "rust_ffi_export",  "ast_pattern": "decorator:no_mangle | decorator:export_name", "file_pattern": "**/*.rs", "enabled": true},
    {"name": "rust_test",        "ast_pattern": "test_file",                         "file_pattern": "**/*.rs",         "enabled": true, "no_propagate": true},
    {"name": "rust_pub_api",     "ast_pattern": "visibility:pub",                    "file_pattern": "**/*.rs",         "enabled": false},
    {"name": "csharp_console_app", "ast_pattern": "function_def:Main | file_is_program", "file_pattern": "**/Program.cs", "enabled": true},
    {"name": "csharp_xunit",     "ast_pattern": "decorator:Fact | decorator:Theory",  "file_pattern": "**/*.cs",         "enabled": true},
    {"name": "csharp_nunit",     "ast_pattern": "decorator:TestFixture | decorator:Test | decorator:TestCase | decorator:SetUp | decorator:OneTimeSetUp", "file_pattern": "**/*.cs", "enabled": true},
    {"name": "csharp_mstest",    "ast_pattern": "decorator:TestClass | decorator:TestMethod | decorator:ClassInitialize | decorator:TestInitialize", "file_pattern": "**/*.cs", "enabled": true},
    {"name": "csharp_webapi",    "ast_pattern": "decorator:ApiController | decorator:Route | decorator:HttpGet | decorator:HttpPost | decorator:HttpPut | decorator:HttpDelete | decorator:HttpPatch", "file_pattern": "**/*.cs", "enabled": true},
    {"name": "csharp_minimal_api", "ast_pattern": "function_call:MapGet | function_call:MapPost | function_call:MapPut | function_call:MapDelete | function_call:MapMethods", "file_pattern": "**/*.cs", "enabled": true},
    {"name": "csharp_generic_host", "ast_pattern": "function_call:CreateDefaultBuilder | function_call:ConfigureWebHostDefaults | function_call:Run", "file_pattern": "**/*.cs", "enabled": true},
    {"name": "csharp_winforms",  "ast_pattern": "function_call:Application.Run | function_call:Application.EnableVisualStyles", "file_pattern": "**/*.cs", "enabled": true},
    {"name": "csharp_wpf",       "ast_pattern": "class_definition:App",               "file_pattern": "**/*.cs",         "enabled": true},
    {"name": "csharp_test",      "ast_pattern": "test_file",                         "file_pattern": "**/*.cs",         "enabled": true, "no_propagate": true},
    {"name": "godot_project",    "ast_pattern": "file_match:**/project.godot",        "file_pattern": "**/project.godot", "enabled": true},
    {"name": "godot_editor_tool","ast_pattern": "decorator:@tool",                    "file_pattern": "**/*.gd",          "enabled": true},
    {"name": "godot_rpc_method", "ast_pattern": "decorator:@rpc",                     "file_pattern": "**/*.gd",          "enabled": true},
    {"name": "godot_test",       "ast_pattern": "test_file",                          "file_pattern": "**/*.gd",          "enabled": true, "no_propagate": true}
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
    "dir_patterns": ["tests/", "test/", "__tests__/", "Tests/", "Test/"],
    "file_patterns": ["test_*.py", "*_test.py", "test_*.rs", "*_test.rs", "*Tests.cs", "*Test.cs", "*.Tests.cs", "test_*.gd", "*_test.gd", "test_*.tscn"],
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

- **Scope:** Only affects languages with `public` visibility declarations (Rust `pub`, C# `public`). Has no effect on Python files.
- **Re-indexing:** Toggling the flag triggers a full rebuild (the flag value is stored in the scan stamp). For long-term use, prefer enabling the `rust_pub_api` config rule or adding custom `visibility:pub` entry rules to avoid repeated rebuilds.
- **Config interaction:** Independent of the `rust_pub_api` config rule — the two mechanisms are orthogonal and do not interfere.

#### AST Pattern Prefixes

All rules use the same prefix pattern syntax, supporting OR combinations with ` | `:

| Prefix | Match Target | Example | Languages |
|--------|-------------|---------|-----------|
| `function_call:` | Function call | `"function_call:my_entry"` | Python, C#, C/C++, TS/JS |
| `function_def:` | Function definition name (supports glob) | `"function_def:run_*"` | Python, Rust, C#, C/C++, TS/JS, Godot |
| `decorator:` | Decorator or attribute macro (`#[...]`) / attribute (`[...]`) / GDScript annotation (`@...`) | `"decorator:app.route"` / `"decorator:tokio::main"` / `"decorator:Fact"` / `"decorator:@tool"` | Python, Rust, C#, TS/JS, Godot |
| `class_instantiation:` | Class instantiation | `"class_instantiation:MyApp"` | Python, TS/JS |
| `class_definition:` | Class/struct/record/interface definition (supports glob) | `"class_definition:App"` | C#, C/C++, TS/JS |
| `file_match:` | Filename match | `"file_match:**/main.py"` | Python, Rust, C#, C/C++, TS/JS, Godot |
| `file_is_program` | `Program.cs` with top-level statements | `"file_is_program"` | C# |
| `if_name_main` | `if __name__ == '__main__'` check | `"if_name_main"` | Python |
| `test_file` | Test file detection (uses `test_patterns` config) | `"test_file"` | Python, Rust, C#, C/C++, TS/JS, Godot |
| `visibility:pub` | Items with `pub` visibility modifier | `"visibility:pub"` | Rust |
| `visibility:public` | Items with `public` visibility modifier | `"visibility:public"` | C# |
| `trait_impl:` | Trait implementation block | `"trait_impl:Default"` | Rust |
| `macro_def:` | `macro_rules!` definition | `"macro_def:my_macro"` | Rust |
| `jsx_element:` | JSX element | `"jsx_element:App"` | TS/JS |
| `export:` | ES module export | `"export:default"` | TS/JS |

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

### godot — Godot Settings

Settings for the GDScript / Godot adapter. All keys are optional; the defaults below are the ones shipped in `DEFAULT_CONFIG`.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `public_class_api` | `bool` | `true` | Treat a script declaring `class_name X` as a public API entry (a script that IS a reusable class). Disable for a game — or a project where only scenes decide what is used — so a class no scene references can be reported dead. |
| `method_dead_code` | `bool` | `false` | Report per-method dead code. Off by default: Godot reaches methods through `call("name")`, editor-written `[connection]` entries and string-built `Callable`s, so a per-method verdict is not provable in general. |
| `signal_dead_code` | `bool` | `false` | Report a declared `signal` that nothing connects to or emits. Off by default for the same reason (connections can be made at runtime from a string). |
| `constant_dead_code` | `bool` | `false` | Report a `const` that nothing reads. Off by default because constants are also read through `ProjectSettings`/reflection-style lookups. |
| `assume_dynamic_keeps_file_alive` | `bool` | `true` | When a script contains something unprovable (`load(variable)`, `get_node(variable)`, `call(variable)`, `Expression.parse`, …) keep every member of that script alive instead of guessing. Set to `false` to narrow liveness and accept the extra false positives; the script still receives a `dynamic_import` warning. |
| `dispatch_keepalive` | `bool` | `true` | Treat a literal string dispatch name (`call("add_score")`, `emit_signal("died")`, `set("prop")`) and every `.tscn` `[connection]` `signal`/`method` as an entry, so the target member is not reported dead. |

```json
{
  "godot": {
    "public_class_api": false,
    "method_dead_code": true
  }
}
```

Godot entry rules (see `entry_rules`): `godot_project` (the `project.godot` manifest — its `read` edges reach the main scene and every autoload), `godot_editor_tool` (`@tool`), `godot_rpc_method` (`@rpc`), `godot_test` (`no_propagate`, so a test script is alive but does not keep the code it touches alive).

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
