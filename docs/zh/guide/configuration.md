# 配置指南

graphlint 的配置文件位于项目根目录的 `.graphlint/config.json`，使用 JSON 格式。

## 默认配置

```json
{
  "entry_rules": [
    {"name": "python_main",      "ast_pattern": "if __name__ == '__main__'",        "file_pattern": "**/*.py",         "enabled": true},
    {"name": "python_package",   "ast_pattern": "file-level: all module-level nodes",  "file_pattern": "**/__init__.py","enabled": true},
    {"name": "fastapi_app",      "ast_pattern": "FastAPI instantiation OR uvicorn.run call", "file_pattern": "**/*.py", "enabled": true},
    {"name": "flask_app",        "ast_pattern": "Flask instantiation OR app.run call", "file_pattern": "**/*.py",      "enabled": true},
    {"name": "django_manage",    "ast_pattern": "execute_from_command_line call",    "file_pattern": "**/manage.py",    "enabled": true},
    {"name": "click_command",    "ast_pattern": "click.command or click.group decorator", "file_pattern": "**/*.py",  "enabled": true},
    {"name": "typer_app",        "ast_pattern": "typer.Typer instantiation",         "file_pattern": "**/*.py",         "enabled": true},
    {"name": "celery_app",       "ast_pattern": "celery.Celery instantiation",       "file_pattern": "**/*.py",         "enabled": true},
    {"name": "pytest_plugin",    "ast_pattern": "pytest_addoption or pytest.fixture", "file_pattern": "**/conftest.py", "enabled": true},
    {"name": "pytest_test",      "ast_pattern": "test_* functions / Test* classes in test files", "file_pattern": "**/*.py", "enabled": true}
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

## 配置详解

### entry_rules — 入口检测规则

定义如何自动检测代码入口点。每条规则包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `string` | 规则唯一名称 |
| `ast_pattern` | `string` | AST 匹配模式（内置规则使用描述文本，自定义规则使用前缀模式） |
| `file_pattern` | `string` | 匹配文件名的 glob 模式 |
| `description` | `string` | 规则描述（可选） |
| `enabled` | `boolean` | 是否启用 |

#### 自定义 AST 模式前缀

自定义规则支持以下前缀模式：

| 前缀 | 匹配目标 | 示例 |
|------|----------|------|
| `function_call:` | 函数调用 | `"function_call:my_entry"` |
| `function_def:` | 函数名匹配（支持 glob） | `"function_def:run_*"` |
| `decorator:` | 装饰器 | `"decorator:app.route"` |
| `class_instantiation:` | 类实例化 | `"class_instantiation:MyApp"` |
| `file_match:` | 文件名匹配 | `"file_match:**/main.py"` |

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
