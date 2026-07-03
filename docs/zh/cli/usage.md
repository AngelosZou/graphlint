# CLI 使用指南

`graphlint` 命令行工具提供五个子命令：`query`、`build`、`install`、`uninstall` 和 `config`。

## 全局选项

```
usage: graphlint [-h] {query,build,install,uninstall,config} ...
```

- `-h, --help` — 显示帮助信息

## query — 查询依赖图

查询子命令用于检索和分析代码依赖关系图。

### 基本用法

```bash
graphlint query                    # 分析当前目录
graphlint query -r /path/to/proj   # 分析指定项目
graphlint query -j                 # JSON 格式输出
```

### 选项详解

| 选项 | 简写 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--include-tests` | `-t` | 标志 | `false` | 包含测试文件中的节点 |
| `--exclude-clean` | `-C` | 标志 | `false` | 排除无异常的图（仅显示有警告/错误的图） |
| `--reachability` | `-R` | 标志 | `false` | 仅返回从入口经 CALL 边可达的图 |
| `--dead-code-tests` | — | 标志 | `false` | 查询引用已死代码的测试 |
| `--graph-id` | `-g` | 整数 | — | 查看指定图的详细信息 |
| `--json` | `-j` | 标志 | `false` | 以结构化 JSON 格式输出 |
| `--path-format` | `-p` | 选择 | `relative` | 路径格式：`absolute` / `relative` |
| `--root-dir` | `-r` | 字符串 | `.` | 指定目标项目根目录 |
| `--max-results` | `-n` | 整数 | `50` | 最大返回图数量（1–1000） |
| `--min-nodes` | — | 整数 | `0` | 只返回节点数 ≥ N 的图 |
| `--max-nodes` | — | 整数 | — | 只返回节点数 ≤ N 的图 |
| `--warn-types` | `-w` | 字符串 | — | 逗号分隔的警告类型过滤 |
| `--sort-by` | — | 选择 | `warnings` | 排序方式：`warnings` / `nodes` / `edges` / `name` |
| `--detail` | `-d` | 选择 | `auto` | 详细程度：`auto` / `summary` / `full` / `minimal` |
| `--output-limit` | — | 整数 | `8000` | 输出文本长度限制（字符，100–100000） |
| `--edge-limit` | — | 整数 | `10` | 单图详情最大显示的边数（0=不限制） |
| `--file-limit` | — | 整数 | `10` | 单图详情最大显示的文件数（0=不限制） |
| `--node-limit` | — | 整数 | `30` | 单图详情最大显示的节点数（0=不限制） |
| `--no-scan` | — | 标志 | `false` | 跳过自动扫描/构建，直接查询已有索引 |

### 示例

```bash
# 查看第 3 个图的完整详情
graphlint query -g 3 --detail full

# 仅显示有 5 个以上节点且按警告数排序的结果
graphlint query --min-nodes 5 --sort-by warnings

# 仅查询循环引用警告
graphlint query -w "circular_ref"

# 无自动扫描模式（适用于只读查询）
graphlint query --no-scan
```

## install — 安装 Agent 提示词（全局）

将 graphlint 的使用提示词安装到 AI 编码工具的**全局配置**中，让每个项目自动获得 graphlint 的使用指南。

### 用法

```bash
graphlint install
```

运行交互式选择器，选择一个或多个工具（opencode → `~/.config/opencode/AGENTS.md`、cursor → `~/.cursorrules`、codex → `~/.codex/rules/graphlint.md`、cc → `~/.claude/CLAUDE.md`）。详见 [Agent 集成](../guide/agent-integration.md)。

## uninstall — 卸载 Agent 提示词

从 AI 编码工具中移除 graphlint 的使用提示词。

### 用法

```bash
graphlint uninstall
```

扫描全局配置文件中的已安装提示词，交互式移除。

## build — 构建/重建索引

构建子命令用于扫描文件并构建或更新依赖图索引。

### 基本用法

```bash
graphlint build              # 增量构建
graphlint build --force      # 全量重建
graphlint build -P 4         # 4 个并行 worker
```

### 选项详解

| 选项 | 简写 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--force` | `-f` | 标志 | `false` | 强制全量重建（忽略增量缓存） |
| `--parallel` | `-P` | 整数 | `0` | 并行 worker 数（0=自动检测 CPU，最大 64） |

### 输出说明

构建完成后返回 JSON 格式的统计信息：

```json
{
  "status": "ok",
  "files_scanned": 150,
  "files_changed": 12,
  "files_added": 3,
  "files_removed": 1,
  "nodes_added": 45,
  "edges_updated": 120,
  "duration_ms": 320,
  "warnings_generated": 8
}
```

## config — 配置管理

配置子命令用于查看和修改 `.graphlint/config.json` 配置文件。

### 子命令

| 命令 | 说明 |
|------|------|
| `show` | 显示当前配置 |
| `get --key <key>` | 获取指定配置项的值 |
| `set --key <key> --value <val>` | 设置指定配置项 |
| `copy-from --from <source>` | 从源目录复制配置 |
| `add-entry-rule --rule-json <json>` | 添加自定义入口检测规则 |
| `remove-entry-rule --name <name>` | 移除入口检测规则 |
| `add-exclude --exclude-pattern <pat>` | 添加排除模式 |
| `remove-exclude --exclude-pattern <pat>` | 移除排除模式 |

### 示例

```bash
# 显示配置
graphlint config show

# 切换语言
graphlint config set --key lang --value en

# 添加自定义入口规则
graphlint config add-entry-rule --rule-json '{"name":"my_cli","ast_pattern":"class_instantiation:click.Group","file_pattern":"**/cli.py","enabled":true}'

# 添加排除模式
graphlint config add-exclude --exclude-pattern "migrations/"
```
