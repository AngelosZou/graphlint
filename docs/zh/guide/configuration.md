# 配置指南

graphlint 的配置文件位于项目根目录的 `.graphlint/config.json`，使用 JSON 格式。

## 默认配置

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

## 配置详解

### entry_rules — 入口检测规则

定义如何自动检测代码入口点。每条规则包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `string` | 规则唯一名称 |
| `ast_pattern` | `string` | AST 匹配模式（使用统一前缀语法，内置规则与自定义规则一致） |
| `file_pattern` | `string` | 匹配文件名的 glob 模式 |
| `description` | `string` | 规则描述（可选） |
| `enabled` | `boolean` | 是否启用 |
| `no_propagate` | `boolean` | 入口点不传播可达性（默认 `false`，如 pytest 测试规则设为 `true`） |

**注意：** `rust_pub_api` 规则（模式 `visibility:pub`，仅限 Rust）**默认禁用**（`"enabled": false`）。在查询时使用 `--public-as-entry`，或手动在配置中设为 `"enabled": true` 以实现持久的库代码分析。

### --public-as-entry 标志

`--public-as-entry` CLI 标志（或 API 参数 `public_as_entry=True`）将所有公开项视为执行入口点：

```bash
graphlint query --public-as-entry
```

- **适用范围：** 仅影响具有 `public` 可见性声明的语言（Rust `pub`），对 Python 文件无效。
- **重新索引：** 开关此标志会触发全量重建（标志值存储在扫描戳中）。长期使用建议启用 `rust_pub_api` 配置规则或添加自定义 `visibility:pub` 入口规则，以避免反复重建。
- **配置交互：** 与 `rust_pub_api` 配置规则独立——两者是正交的机制，互不干扰。

#### AST 模式前缀

所有规则使用统一的前缀模式语法，支持 ` | ` 分隔的 OR 组合：

| 前缀 | 匹配目标 | 示例 | 适用语言 |
|------|----------|------|----------|
| `function_call:` | 函数调用 | `"function_call:my_entry"` | Python |
| `function_def:` | 函数定义名（支持 glob） | `"function_def:run_*"` | Python、Rust |
| `decorator:` | 装饰器或属性宏（`#[...]`） | `"decorator:app.route"` / `"decorator:tokio::main"` | Python、Rust |
| `class_instantiation:` | 类实例化 | `"class_instantiation:MyApp"` | Python |
| `file_match:` | 文件名匹配 | `"file_match:**/main.py"` | Python、Rust |
| `if_name_main` | `if __name__ == '__main__'` 检测 | `"if_name_main"` | Python |
| `test_file` | 测试文件检测（使用 `test_patterns` 配置） | `"test_file"` | Python、Rust |
| `visibility:pub` | 匹配具有 `pub` 可见性修饰符的项目 | `"visibility:pub"` | Rust |
| `trait_impl:` | 匹配 `impl Trait for Type` 实现块 | `"trait_impl:Default"` | Rust |
| `macro_def:` | 匹配 `macro_rules!` 定义 | `"macro_def:my_macro"` | Rust |

### exclude_patterns — 排除模式

| 字段 | 类型 | 说明 |
|------|------|------|
| `always_exclude` | `string[]` | 始终排除的目录/文件模式（不可修改） |
| `user_exclude` | `string[]` | 用户自定义排除模式（可通过 CLI 或 API 管理） |

### lang — 语言设置

支持的值：
- `"system"` — 跟随系统语言（自动检测）
- `"zh_CN"` — 简体中文
- `"en"` — 英语

### output — 输出设置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `default_detail` | `string` | `"auto"` | 默认详细程度：`"auto"` / `"summary"` / `"full"` / `"minimal"` |
| `default_max_results` | `int` | `50` | 默认最大返回结果数 |
| `default_output_limit` | `int` | `8000` | 文本输出字符数限制 |

### performance — 性能设置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `hash_algorithm` | `string` | `"sha256"` | 文件内容哈希算法 |
| `max_file_size_mb` | `int` | `10` | 超过此大小的文件将被跳过 |
| `parallel_workers` | `int` | `0` | 并行 worker 数（0=自动） |

### test_patterns — 测试文件识别模式

| 字段 | 类型 | 说明 |
|------|------|------|
| `config_files` | `string[]` | 测试配置文件匹配 |
| `dir_patterns` | `string[]` | 测试目录匹配模式 |
| `file_patterns` | `string[]` | 测试文件名匹配模式 |
| `function_patterns` | `string[]` | 测试函数匹配模式 |

## 配置管理方式

### 方式 1：CLI

```bash
# 查看配置
graphlint config show

# 设置配置
graphlint config set --key lang --value zh_CN

# 添加入口规则
graphlint config add-entry-rule --rule-json '{"name":"my_app","ast_pattern":"function_call:start","file_pattern":"**/app.py"}'

# 添加排除模式
graphlint config add-exclude --exclude-pattern "generated/"
```

### 方式 2：Python API

```python
from graphlint.api import configure

# 查看配置
configure(action="show")

# 设置配置
configure(action="set", key="performance.max_file_size_mb", value="20")
```

### 方式 3：直接编辑

直接修改 `.graphlint/config.json` 文件。修改后下次查询或构建时自动生效。

## 配置优先级

1. Python API 调用参数（最高）
2. CLI 命令行参数
3. `.graphlint/config.json` 配置文件
4. 内置默认值（最低）
