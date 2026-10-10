# 配置指南

graphlint 的配置文件位于项目根目录的 `.graphlint/config.json`，使用 JSON 格式。

## 默认配置

```json
{
  "entry_rules": [
    {"name": "python_main",      "ast_pattern": "if_name_main",                      "file_pattern": "**/*.py",         "enabled": true},
    {"name": "python_package",   "ast_pattern": "file_match:**/__init__.py",         "file_pattern": "**/__init__.py",  "enabled": true},
    {"name": "fastapi_app",      "ast_pattern": "class_instantiation:FastAPI | function_call:uvicorn.run", "file_pattern": "**/*.py", "enabled": true},
    {"name": "flask_app",        "ast_pattern": "class_instantiation:Flask | class_instantiation:flask.Flask | function_call:app.run", "file_pattern": "**/*.py", "enabled": true},
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
  "version": 2
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

- **适用范围：** 仅影响具有 `public` 可见性声明的语言（Rust `pub`、C# `public`），对 Python 文件无效。
- **重新索引：** 开关此标志会触发全量重建（标志值存储在扫描戳中）。长期使用建议启用 `rust_pub_api` 配置规则或添加自定义 `visibility:pub` 入口规则，以避免反复重建。
- **配置交互：** 与 `rust_pub_api` 配置规则独立——两者是正交的机制，互不干扰。

#### AST 模式前缀

所有规则使用统一的前缀模式语法，支持 ` | ` 分隔的 OR 组合：

| 前缀 | 匹配目标 | 示例 | 适用语言 |
|------|----------|------|----------|
| `function_call:` | 函数调用 | `"function_call:my_entry"` | Python、C#、C/C++、TS/JS |
| `function_def:` | 函数定义名（支持 glob） | `"function_def:run_*"` | Python、Rust、C#、C/C++、TS/JS、Godot |
| `decorator:` | 装饰器或属性宏（`#[...]`）/ 特性（`[...]`）/ GDScript 注解（`@...`） | `"decorator:app.route"` / `"decorator:tokio::main"` / `"decorator:Fact"` / `"decorator:@tool"` | Python、Rust、C#、TS/JS、Godot |
| `class_instantiation:` | 类实例化 | `"class_instantiation:MyApp"` | Python、TS/JS |
| `class_definition:` | 类/结构体/记录/接口定义（支持 glob） | `"class_definition:App"` | C#、C/C++、TS/JS |
| `file_match:` | 文件名匹配 | `"file_match:**/main.py"` | Python、Rust、C#、C/C++、TS/JS、Godot |
| `file_is_program` | 含顶级语句的 `Program.cs` | `"file_is_program"` | C# |
| `if_name_main` | `if __name__ == '__main__'` 检测 | `"if_name_main"` | Python |
| `test_file` | 测试文件检测（使用 `test_patterns` 配置） | `"test_file"` | Python、Rust、C#、C/C++、TS/JS、Godot |
| `visibility:pub` | 匹配具有 `pub` 可见性修饰符的项目 | `"visibility:pub"` | Rust |
| `visibility:public` | 匹配具有 `public` 可见性修饰符的项目 | `"visibility:public"` | C# |
| `trait_impl:` | 匹配 `impl Trait for Type` 实现块 | `"trait_impl:Default"` | Rust |
| `macro_def:` | 匹配 `macro_rules!` 定义 | `"macro_def:my_macro"` | Rust |
| `jsx_element:` | JSX 元素 | `"jsx_element:App"` | TS/JS |
| `export:` | ES 模块导出 | `"export:default"` | TS/JS |

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

### godot — Godot 设置

GDScript / Godot 分析器的设置。所有键均可选，下表为 `DEFAULT_CONFIG` 中的默认值。

| 键 | 类型 | 默认值 | 说明 |
|-----|------|---------|-------------|
| `public_class_api` | `bool` | `true` | 将声明了 `class_name X` 的脚本视为公开 API 入口（脚本本身即一个可复用类）。游戏项目、或「只有场景决定什么被使用」的项目可关闭，让没有任何场景引用的类可被判为死代码。 |
| `method_dead_code` | `bool` | `false` | 是否报告方法级死代码。默认关闭：Godot 会通过 `call("name")`、编辑器写入的 `[connection]` 连线以及字符串构造的 `Callable` 触达方法，因此方法级结论通常无法静态证明。 |
| `signal_dead_code` | `bool` | `false` | 是否报告「无人连接、也无人 emit」的 `signal`。默认关闭，原因同上（连接可在运行时由字符串建立）。 |
| `constant_dead_code` | `bool` | `false` | 是否报告无人读取的 `const`。默认关闭，因为常量也可能通过 `ProjectSettings`／反射式查找读取。 |
| `assume_dynamic_keeps_file_alive` | `bool` | `true` | 当脚本中存在无法证明的构造（`load(变量)`、`get_node(变量)`、`call(变量)`、`Expression.parse` 等）时，保守地保留该脚本的全部成员，而不是去猜。设为 `false` 可收窄存活范围并接受更多假阳性；该脚本仍会收到 `dynamic_import` 提示。 |
| `dispatch_keepalive` | `bool` | `true` | 将字面量字符串分发名（`call("add_score")`、`emit_signal("died")`、`set("prop")`）以及 `.tscn` 中每个 `[connection]` 的 `signal`/`method` 视为入口，目标成员不会被判为死代码。 |

```json
{
  "godot": {
    "public_class_api": false,
    "method_dead_code": true
  }
}
```

Godot 入口规则（见 `entry_rules`）：`godot_project`（`project.godot` 工程清单 —— 它的 `read` 边抵达主场景与全部 autoload）、`godot_editor_tool`（`@tool`）、`godot_rpc_method`（`@rpc`）、`godot_test`（`no_propagate`：测试脚本自身存活，但不让它触达的代码随之存活）。

### version — 默认模板版本

`version` 记录该配置文件是从哪个版本的默认模板生成的。`.graphlint/config.json` 只在首次运行时写入一次，此后它就是你项目的唯一依据：由于 `entry_rules` 是整份列表取自你的文件（而不是逐条合并），你删掉的规则会保持删除状态。`version` 的作用是让 graphlint 能在自带的默认模板发生变化时提示你 —— 见下文。

## 配置管理方式

### 方式 1：CLI

```bash
# 查看配置
graphlint config show

# 与当前默认模板对比
graphlint config diff

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

### 升级已有配置

当某个 graphlint 版本改动了默认模板（例如收窄了某条入口规则），你已有的 `config.json` 会保留不变。下一次 `query` / `build` / `config` 运行会在 stderr 打印一次性提示：

```
[graphlint] 默认规则模板已更新（模板 v1 → v2）。运行 'graphlint config diff' 可查看具体差异。
```

`graphlint config diff` 展示你的文件与当前默认模板的差异：

```bash
graphlint config diff
```

| 报告项 | 含义 |
|--------|------|
| `template_version` | 你的文件记录的 `version` 与当前默认版本，以及是否落后 |
| `entry_rules.removed` | 你删除的默认规则 —— graphlint **不会**把它们加回来 |
| `entry_rules.added` | 你自行新增、默认模板中没有的规则 |
| `entry_rules.overridden` | 你改动过的默认规则，逐字段给出默认值与你的值 |
| `keys` | 其他存在差异的顶层键（如 `lang`、`godot`、`performance`） |

采纳模板改动请显式操作：自行编辑该规则，或删除 `config.json` 让 graphlint 用当前默认模板重新生成（会丢弃你的自定义）。提示每个模板版本只出现一次，记录写在 `.graphlint/.template_notice.json`。

## 配置优先级

1. Python API 调用参数（最高）
2. CLI 命令行参数
3. `.graphlint/config.json` 配置文件
4. 内置默认值（最低）
