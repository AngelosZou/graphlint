# graphlint

[![PyPI](https://img.shields.io/pypi/v/graphlint)](https://pypi.org/project/graphlint/)
[![Python](https://img.shields.io/pypi/pyversions/graphlint)](https://pypi.org/project/graphlint/)
[![License](https://img.shields.io/pypi/l/graphlint)](https://github.com/AngelosZou/graphlint/blob/main/LICENSE)

[![en](https://img.shields.io/badge/lang-en-red.svg)](../../README.md)
[![zh](https://img.shields.io/badge/lang-zh--CN-blue.svg)](README.md)

**面向 AI 生成 Python 代码库的死代码检测工具。**

AI Agent 在快速生成代码的同时，也会留下大量冗余和死代码。这些代码污染了 LLM 的上下文窗口，稀释了注意力。Graphlint 通过分析代码库的依赖关系图，识别入口点并**检测死代码**（从任何入口点均不可达的组件），让 Agent 能够自行清理，保持代码库的简洁高效。

## 特性

- **死代码检测** — 通过图遍历找出所有入口点不可达的组件
- **AST 解析** — 提取类、函数、方法、变量、字段
- **依赖图构建** — 有向边：`read`、`write`、`call`、`inherit`、`decorate`
- **入口点检测** — 10 种内置规则（main、FastAPI、Flask、Django、Click、Typer、Celery、pytest、包入口和测试入口）及自定义规则
- **警告检测** — 11 种警告类型：循环引用、未使用 import、只写变量、死代码等
- **Python API + CLI** — 可集成到任何 Tool 开发、CI 流程，或直接供 Agent 自行分析和清理

## 安装

```bash
pip install graphlint
```

**要求：** Python >= 3.9

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

运行 `graphlint install` 并选择您使用的工具 — 提示词（使用场景、核心命令、关键参数）将被添加到全局配置中。详见 [Agent 集成](guide/agent-integration.md)。

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

- **纯静态分析** — graphlint 基于静态分析执行，无法检测 `getattr`、`importlib` 等运行时动态链接或动态分发模式，这可能会导致假阳性。**缓解方案：** 根据代码库的实际约定添加自定义入口规则。例如，graphlint 自身的代码库使用了 `function_def:_detect_*` 和 `function_def:visit_*` 两种 ast_pattern，防止通过 `getattr` 发现的函数被误报为死代码。
- **大规模代码库构建耗时** — 在包含 700+ 个 Python 文件、1,000+ 个类定义和 14,000+ 个函数的大规模代码库上，完整重构需要约 200 秒（实际时间与设备性能有关）。小型项目（~60 个文件）约 1 秒完成。**最佳实践：** 在改动前运行 `query` 了解现状并规划方案，改动期间避免执行 `query` 以防止不必要地触发索引重构。

## 许可证

MIT — 详见 [LICENSE](LICENSE)。

## 链接

- [GitHub 仓库](https://github.com/AngelosZou/graphlint)
- [问题追踪](https://github.com/AngelosZou/graphlint/issues)
- [PyPI 包](https://pypi.org/project/graphlint/)
