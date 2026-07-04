# 快速开始

graphlint 面向 AI Agent 大量生成代码后产生冗余代码的场景。它通过分析代码库的依赖关系图，找出从任何入口点均不可达的死代码 — 这些代码污染 LLM 上下文窗口、稀释注意力，是 Agent 自清理的关键目标。

graphlint 提供 **Python API**（可集成到任何 Tool 开发中）和 **CLI**（可用于 CI 流程，或直接由 Agent 命令行调用让 Agent 自行分析和清理）。

## 安装

```bash
pip install graphlint
```

要求：Python ≥ 3.9，零第三方依赖。

## Agent 集成

Graphlint 可以将使用提示词注入到您的 AI 编码工具的**全局配置**中，让每个项目自动获得 graphlint 的使用指南：

```bash
# 交互式安装：将一个或多个 Agent 工具的提示词安装
graphlint install

# 交互式卸载：从 Agent 工具中移除提示词
graphlint uninstall
```

执行 `install` 时，会提示您选择要安装的工具及其全局配置路径：

| 工具 | 全局配置文件 |
|------|-------------|
| **OpenCode CLI** | `~/.config/opencode/AGENTS.md` |
| **Cursor Editor** | `~/.cursorrules` |
| **Codex CLI** | `~/.codex/rules/graphlint.md` |
| **Claude Code (CLI)** | `~/.claude/CLAUDE.md` |

安装的提示词包括使用场景（修改后清理、分析前审计）、核心命令（`query`、`build`、`config`）、关键参数（`-g`、`--json`、`-w`、`-d` 等）及使用示例。

详见 [Agent 集成](agent-integration.md)。

## CLI 快速使用

### 查询依赖图

```bash
# 分析当前目录，输出依赖图列表
graphlint query

# JSON 格式输出
graphlint query --json

# 查看指定图详情
graphlint query -g 1 --detail full

# 包含测试文件
graphlint query --include-tests

# 限定最大结果数
graphlint query --max-results 10

# 按节点数排序
graphlint query --sort-by nodes

# 过滤警告类型
graphlint query --warn-types "circular_ref,unused_import"
```

### 构建/重建索引

```bash
# 增量构建（仅解析变更文件）
graphlint build

# 强制全量重建
graphlint build --force

# 并行构建（自动检测 CPU 核心数）
graphlint build --parallel 0
```

### 配置管理

```bash
# 查看当前配置
graphlint config show

# 设置语言为简体中文
graphlint config set --key lang --value zh_CN

# 获取配置项
graphlint config get --key lang

# 从其他目录复制配置
graphlint config copy-from --from /path/to/project

# 添加入口检测规则
graphlint config add-entry-rule --rule-json '{"name":"my_app","ast_pattern":"function_call:my_entry","file_pattern":"**/main.py"}'

# 移除入口规则
graphlint config remove-entry-rule --name my_app

# 添加排除模式
graphlint config add-exclude --exclude-pattern "generated/"

# 移除排除模式
graphlint config remove-exclude --exclude-pattern "generated/"
```

## Python API 快速使用

### 基本查询

```python
from graphlint.api import query, build, configure

# 查询依赖图（文本格式）
result = query()
print(result)

# 查询依赖图（JSON 格式）
result = query(
    include_tests=True,
    json_output=True,
    max_results=20,
    sort_by="warnings",
)
print(result)

# 查询指定图的详细信息
detail = query(graph_id=1, detail_level="full", json_output=True)
print(detail)
```

### 构建索引

```python
from graphlint.api import build

# 增量构建
stats = build()
print(f"扫描文件: {stats['files_scanned']}")
print(f"变更文件: {stats['files_changed']}")
print(f"新增节点: {stats['nodes_added']}")

# 强制重建
stats = build(force_rebuild=True, parallel=4)
```

### 配置管理

```python
from graphlint.api import configure

# 查看配置
result = configure(action="show")
print(result["config"])

# 设置配置
configure(action="set", key="lang", value="en")

# 获取配置项
result = configure(action="get", key="lang")
print(result["value"])
```

### 惰性导入

`graphlint` 包支持惰性导入，仅在首次访问时加载相应模块：

```python
import graphlint

# __version__ 为模块常量，可直接访问
print(graphlint.__version__)  # "0.1.4"

# query / build / configure 在首次访问时惰性导入
result = graphlint.query()       # 首次调用时延迟导入
stats = graphlint.build()        # 同上
cfg = graphlint.configure(action="show")
```

## 更多示例

### 在 CI/CD 中使用

```bash
#!/bin/bash
# 检查循环引用
graphlint query --warn-types "circular_ref" --json | grep -q "circular_ref" && echo "发现循环引用！" || echo "通过"
```

### 与代码质量工具集成

```python
from graphlint.api import query

# 检查未使用的导入
result = query(
    warn_types="unused_import",
    json_output=True,
)

# 分析结果
if isinstance(result, dict):
    for graph in result.get("graphs", []):
        if graph.get("warnings"):
            print(f"图 #{graph['graph_id']}({graph['name']}): {len(graph['warnings'])} 个警告")
```
