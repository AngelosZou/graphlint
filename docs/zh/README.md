# graphlint

[![PyPI](https://img.shields.io/pypi/v/graphlint)](https://pypi.org/project/graphlint/)
[![Python](https://img.shields.io/pypi/pyversions/graphlint)](https://pypi.org/project/graphlint/)
[![License](https://img.shields.io/pypi/l/graphlint)](https://github.com/AngelosZou/graphlint/blob/main/LICENSE)

[English](../../README.md) | [简体中文](README.md)

**面向 AI 生成代码库的死代码检测工具。**

AI Agent 在快速生成代码的同时，也会留下大量冗余和死代码。这些代码污染了 LLM 的上下文窗口，稀释了注意力。Graphlint 通过分析代码库的依赖关系图，识别入口点并**检测死代码**（从任何入口点均不可达的组件），让 Agent 能够自行清理，保持代码库的简洁高效。

## 支持的语言

| 语言 | 状态 | 解析器 | 特性 |
|------|------|--------|------|
| **Python** (`.py`) | 内置 | `ast`（标准库） | 装饰器、类型注解、动态导入、框架感知入口检测 |
| **Rust** (`.rs`) | 内置（可选依赖） | `tree-sitter` | 属性宏、Trait、`pub` 可见性、`macro_rules!` |

安装含 Rust 支持的版本：`pip install graphlint[rust]`（额外引入 `tree-sitter` 和 `tree-sitter-rust`）。

## 特性

- **死代码检测** — 通过图遍历找出所有入口点不可达的组件
- **多语言支持** — Python 和 Rust 后端，通过语言适配器抽象层实现；Python 使用标准库 `ast`，Rust 使用 `tree-sitter`
- **语言专有特性感知** — Python 装饰器、Rust 属性宏（`#[tokio::main]`、`#[test]`）、Trait 实现、`pub` 可见性等
- **AST/CST 解析** — 提取函数、方法、结构体、枚举、Trait、实现块、宏、变量、字段；感知类型声明，自动处理循环解包等变量绑定
- **依赖图构建** — 有向边：`read`、`write`、`call`、`inherit`、`decorate`
- **入口点检测** — 17 种内置规则，覆盖 Python 框架（FastAPI、Flask、Django、Click、Typer、Celery、pytest）和 Rust 惯例（main、异步运行时、WASM、proc 宏、FFI、测试、pub API）及自定义规则
- **可配置入口模板** — 通过 `ast_pattern` 前缀添加自定义入口规则，包括 `function_call:`、`function_def:`、`decorator:`、`file_match:`、`visibility:pub`（Rust）、`trait_impl:`（Rust）、`macro_def:`（Rust）等
- **`--public-as-entry` 标志** — 将所有公开项（Rust `pub`）视为入口点，用于库代码分析
- **警告检测** — 11 种警告类型：循环引用、未使用 import、只写变量、死代码等
- **Python API + CLI** — 可集成到任何 Tool 开发、CI 流程，或直接供 Agent 自行分析和清理

## 安装

```bash
pip install graphlint
```

**要求：** Python >= 3.9

如需支持 Rust（`.rs` 文件），安装可选的 `tree-sitter` 依赖：

```bash
pip install graphlint[rust]
```

## 快速开始

### Agent 集成

Graphlint 提供命令将其使用提示词注入到 AI 编码工具的**全局配置**中，让每个项目自动获得 graphlint 的使用指南：

```bash
# 将 graphlint 提示词安装到 Agent 工具（opencode, cursor, codex, cc）
graphlint install

# 将提示词复制到粘贴板，供手动粘贴到 Agent
graphlint prompt

# 从 Agent 工具中移除 graphlint 提示词
graphlint uninstall
```

运行 `graphlint install` 并选择你使用的工具 — 提示词（使用场景、核心命令、关键参数）将被添加到全局配置中。详见 [Agent 集成](guide/agent-integration.md)。

如果你的 Agent 工具未在 install 中列出，可以运行 `graphlint prompt` 将提示词复制到剪贴板并手动提供给 Agent。对于希望添加原生支持的 Agent，欢迎提交 [issue](https://github.com/AngelosZou/graphlint/issues) —— 这类需求通常会被快速响应。

### CLI

```bash
# 查找当前目录的死代码
graphlint query --warn-types "dead_code"

# 完整分析（JSON 输出）
graphlint query --json

# 查看指定图详情
graphlint query -g 1 --detail full

# 检测到死代码或循环引用时返回非零退出码（用于 CI）
graphlint query --json --fail-on dead_code,circular_ref

# 将所有公开项视为入口点（库模式分析）
graphlint query --public-as-entry

# 重建索引
graphlint build --force

# 配置管理
graphlint config show
graphlint config set --key lang --value zh_CN
```

### 退出码

| 码 | 含义 |
|------|---------|
| `0` | 成功 — 未匹配到 `--fail-on` 指定的警告 |
| `1` | 错误 — 参数无效、异常或配置错误 |
| `2` | 发现警告 — `--fail-on` 匹配到指定警告类型 |

使用 `--fail-on`（逗号分隔的警告类型列表）可使 `graphlint query` 在匹配到指定警告时返回退出码 `2`。这样即可在 CI pipeline 中集成死代码检测，而不会被非关键警告误拦。

Graphlint 基于静态分析，无法识别部分 Python 动态引用（如 `getattr`、`importlib` 等），可能导致非预期的退出码。请仅在确认配置无误后将 `--fail-on` 用于 CI 阻塞行为。Agent 更适合处理需要上下文判断的逻辑。详见[局限性](#局限性)。

### Python API

```python
from graphlint.api import query

# 查找死代码
result = query(warn_types="dead_code", json_output=True)

# 完整的依赖关系图分析
result = query(include_tests=True, json_output=True)
```

## 警告类型

| 警告 | 描述 |
|------|------|
| `unused_import` | 导入的模块或名称未被使用 |
| `dynamic_import` | 通过 importlib 或 `__import__` 动态导入 |
| `circular_ref` | 函数/类之间存在循环依赖 |
| `syntax_error` | 文件存在语法错误 |
| `write_only` | 变量被写入但从未被读取 |
| `deprecated_usage` | 使用了已弃用的函数/类 |
| `dead_code` | 组件从所有入口点均不可达 |
| `type_mismatch` | 可疑的类型注解 |
| `unresolved_ref` | 引用未定义的名称 |
| `unused_variable` | 变量已定义但从未被使用 |
| `file_too_large` | 文件超过配置的大小限制 |

## 开发

```bash
# 克隆仓库
git clone https://github.com/AngelosZou/graphlint.git
cd graphlint

# 创建虚拟环境
python -m venv env
env/Scripts/activate  # Windows
source env/bin/activate  # Unix

# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 运行覆盖率测试
pytest --cov=graphlint

# 运行类型检查
mypy graphlint/

# 运行代码检查
ruff check graphlint/ tests/
```

## 配置

Graphlint 将配置存储在分析目录下的 `.graphlint/config.json` 中。使用 `graphlint config` 命令管理设置，或直接编辑配置文件。

运行 `graphlint config show` 查看完整的默认配置。

## 文档

完整文档见 [docs/zh/](docs/zh/) 目录：

- [快速开始](docs/zh/guide/getting-started.md)
- [Agent 集成](docs/zh/guide/agent-integration.md)
- [配置指南](docs/zh/guide/configuration.md)
- [入口点检测](docs/zh/guide/entry-detection.md)
- [警告参考](docs/zh/guide/warnings.md)
- [CLI 使用](docs/zh/cli/usage.md)
- [架构概览](docs/zh/architecture/overview.md)
- [Python API](docs/zh/api/)

## 局限性

- **纯静态分析** — graphlint 基于静态分析执行，无法检测 `getattr`、`importlib` 等运行时动态链接或动态分发模式，这可能会导致假阳性。此问题主要影响 Python；Rust 的静态分发模型产生的假阳性较少。**缓解方案：** 根据代码库的实际约定添加自定义入口规则。例如，graphlint 自身的代码库使用了 `function_def:_detect_*` 和 `function_def:visit_*` 两种 ast_pattern，防止通过 `getattr` 发现的函数被误报为死代码。
- **Python 动态导入** — 由于 Python 的动态导入机制（`importlib`、`getattr`、元类等），默认入口模板在重度依赖运行时调度的代码库中可能产生假阳性。用户应根据项目约定调整 `entry_rules` 配置。
- **Rust 宏展开** — tree-sitter 解析未展开的源代码；过程宏和 `macro_rules!` 体显示为不透明标记树。部分宏生成的调用路径可能遗漏。`#[derive]` 属性通过隐式 `inherit` 边部分识别。
- **`--public-as-entry` 适用范围** — 此标志仅适用于具有 `public` 可见性声明的语言（Rust `pub`），对 Python 文件无效。开关此标志会触发全量重新索引。对于长期库代码分析，建议通过 `graphlint config` 启用 `rust_pub_api` 入口规则以持久化设置。
- **大规模代码库构建耗时** — 在包含 700+ 个 Python 文件、1,000+ 个类定义和 14,000+ 个函数的大规模代码库上，完整重构需要约 200 秒（实际时间与设备性能有关）。小型项目（~60 个文件）约 1 秒完成。**最佳实践：** 在改动前运行 `query` 了解现状并规划方案，改动期间避免执行 `query` 以防止不必要地触发索引重构。

## 许可证

MIT — 详见 [LICENSE](LICENSE)。

## 链接

- [GitHub 仓库](https://github.com/AngelosZou/graphlint)
- [问题追踪](https://github.com/AngelosZou/graphlint/issues)
- [PyPI 包](https://pypi.org/project/graphlint/)
