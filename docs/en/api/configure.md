# API Reference: configure()

`graphlint.api.configure()` manages the `.graphlint/config.json` configuration.

## Signature

```python
def configure(
    action: str,
    key: Optional[str] = None,
    value: Optional[str] = None,
    source: Optional[str] = None,
    root_dir: str = ".",
    lang: Optional[str] = None,
    rule_json: Optional[str] = None,
    rule_name: Optional[str] = None,
    exclude_pattern: Optional[str] = None,
) -> dict
```

## Parameters

### Common Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `str` | Yes | Configuration action (see below) |
| `root_dir` | `str` | No | Project root directory, default `"."` |

### Actions

| Action | Description | Required Params |
|--------|-------------|-----------------|
| `"show"` | Show full current configuration | None |
| `"get"` | Get the value of a specific config key | `key` |
| `"set"` | Set the value of a specific config key | `key`, `value` |
| `"copy-from"` | Copy configuration from another project | `source` |
| `"add-entry-rule"` | Add a custom entry detection rule | `rule_json` |
| `"remove-entry-rule"` | Remove an entry detection rule | `rule_name` |
| `"add-exclude"` | Add an exclude pattern | `exclude_pattern` |
| `"remove-exclude"` | Remove an exclude pattern | `exclude_pattern` |

### Per-Action Parameter Details

| Parameter | Type | Used By | Description |
|-----------|------|---------|-------------|
| `key` | `Optional[str]` | `get`, `set` | Configuration key name |
| `value` | `Optional[str]` | `set` | Configuration value (auto type conversion) |
| `source` | `Optional[str]` | `copy-from` | Source configuration directory path |
| `rule_json` | `Optional[str]` | `add-entry-rule` | Entry rule JSON string |
| `rule_name` | `Optional[str]` | `remove-entry-rule` | Rule name to remove |
| `exclude_pattern` | `Optional[str]` | `add-exclude`, `remove-exclude` | Exclude pattern string |

## Return Value

All actions return a dict:

```python
{"status": "ok", ...}       # Success
{"status": "error", "message": "..."}  # Failure
```

### show Action

```python
{"status": "ok", "config": {...}}  # config contains full configuration
```

### get Action

```python
{"status": "ok", "key": "lang", "value": "zh_CN"}
```

### set Action

```python
{"status": "ok", "message": "Set lang=zh_CN"}
```

Auto type conversion rules:
- `"true"` / `"yes"` → `True`
- `"false"` / `"no"` → `False`
- Numeric strings → `int` / `float`
- Other → kept as string

### copy-from Action

```python
{"status": "ok", "message": "Configuration copied from /path/to/project"}
```

### add-entry-rule Action

```python
{"status": "ok", "message": "Entry rule added"}
```

`rule_json` format example:
```json
{
  "name": "my_app",
  "ast_pattern": "function_call:my_entry",
  "file_pattern": "**/main.py",
  "description": "Custom entry point",
  "enabled": true
}
```

### remove-entry-rule Action

```python
{"status": "ok", "message": "Entry rule 'my_app' removed"}
```

### add-exclude / remove-exclude Actions

```python
{"status": "ok", "message": "Exclude pattern 'generated/' added"}
```

## Examples

```python
from graphlint.api import configure

# View configuration
result = configure(action="show")
print(result["config"])

# Get a config value
result = configure(action="get", key="lang")
print(f"Current language: {result['value']}")

# Set a config value
configure(action="set", key="lang", value="en")
configure(action="set", key="performance.max_file_size_mb", value="20")

# Copy configuration from another project
configure(action="copy-from", source="/path/to/other/project")

# Add an entry detection rule
configure(
    action="add-entry-rule",
    rule_json='{"name":"my_service","ast_pattern":"class_instantiation:MyApp","file_pattern":"**/service.py"}',
)

# Remove an entry rule
configure(action="remove-entry-rule", rule_name="my_service")

# Add an exclude pattern
configure(action="add-exclude", exclude_pattern="generated/")

# Remove an exclude pattern
configure(action="remove-exclude", exclude_pattern="generated/")
```

## Available Config Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `lang` | `str` | `"system"` | Interface language: `"system"` / `"zh_CN"` / `"en"` |
| `output.default_detail` | `str` | `"auto"` | Default detail level |
| `output.default_max_results` | `int` | `50` | Default max results |
| `output.default_output_limit` | `int` | `8000` | Default output length limit |
| `performance.hash_algorithm` | `str` | `"sha256"` | File hash algorithm |
| `performance.max_file_size_mb` | `int` | `10` | Skip files exceeding this size |
| `performance.parallel_workers` | `int` | `0` | Parallel worker count |
