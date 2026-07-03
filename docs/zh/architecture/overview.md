# 架构概览

graphlint 定位为 AI 生成代码场景下的死代码检测工具。它通过分析依赖关系图，找出从所有入口点均不可达的组件（死代码），帮助 Agent 清理冗余代码、减少上下文污染和注意力稀释。

## 整体架构

graphlint 采用分层模块化架构，各层职责清晰，依赖方向从上层到底层。

```
┌──────────────────────────────────────────────────┐
│                  API 层                            │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ query()  │  │ build()  │  │ configure()   │   │
│  └────┬─────┘  └────┬─────┘  └───────┬───────┘   │
├───────┴─────────────┴─────────────────┴──────────┤
│                  CLI 层                            │
│  ┌─────────────────────────────────────────────┐  │
│  │  graphlint query / build / config           │  │
│  └─────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────┤
│                  业务逻辑层                         │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ Query    │  │Incremen- │  │ ConfigManager │   │
│  │ Engine   │  │talIndexer│  │               │   │
│  └────┬─────┘  └────┬─────┘  └───────┬───────┘   │
├───────┴─────────────┴─────────────────┴──────────┤
│                 分析引擎层                         │
│  ┌─────────┐ ┌────────┐ ┌─────────┐ ┌─────────┐ │
│  │Source   │ │Graph   │ │EntryPt  │ │Warning  │ │
│  │Parser   │ │Builder │ │Detector │ │Collector│ │
│  └────┬────┘ └───┬────┘ └────┬────┘ └────┬────┘ │
│       │          │            │            │      │
│  ┌────┴────┐ ┌───┴────┐ ┌────┴────┐       │      │
│  │ AST     │ │ Graph  │ │Import   │       │      │
│  │Visitor  │ │ Algo   │ │Analyzer │       │      │
│  └─────────┘ └────────┘ └─────────┘       │      │
├────────────────────────────────────────────┴─────┤
│                 存储/持久化层                       │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ Database │  │ Hashing  │  │ Schema        │   │
│  └──────────┘  └──────────┘  └───────────────┘   │
├───────────────────────────────────────────────────┤
│                 基础设施层                          │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ I18n     │  │ Params   │  │ Exceptions    │   │
│  │ Manager  │  │ Defs     │  │               │   │
│  └──────────┘  └──────────┘  └───────────────┘   │
└───────────────────────────────────────────────────┘
```

## 模块职责

### 1. API 层 (`graphlint/api.py`)

提供三个顶级函数作为公共接口：

- **`query()`** — 查询依赖关系图，支持列表/详情模式、文本/JSON 输出、多种筛选条件
- **`build()`** — 构建或重建依赖图索引，支持增量模式和并行处理
- **`configure()`** — 管理配置，支持 show/get/set/copy-from 以及入口规则和排除模式管理

### 2. CLI 层 (`graphlint/cli.py`)

基于 `argparse` 实现命令行接口：

- 三个子命令：`query`、`build`、`config`
- 参数定义与 `params.py` 共享，保证 CLI 与 API 参数一致
- 支持子命令的嵌套（如 `config show`、`config set`）

### 3. 业务逻辑层

- **`QueryEngine`** (`graphlint/query/engine.py`) — 封装 SQLite 查询逻辑，处理图列表、详情、哈希验证、死代码测试查询
- **`IncrementalIndexer`** (`graphlint/incremental/indexer.py`) — 管理增量构建流程，基于 SHA256 哈希判断文件变更
- **`ConfigManager`** (`graphlint/config/manager.py`) — 配置的加载、保存、读取、复制
- **`VolumeStrategy`** (`graphlint/query/volume.py`) — 输出量自适应策略（全量/索引/截断）
- **`TextFormatter`** (`graphlint/query/formatter.py`) — 文本格式化输出

### 4. 分析引擎层

- **`SourceParser`** (`graphlint/analyzer/parser.py`) — 递归扫描目录，对每个 `.py` 文件执行 AST 解析
- **`GraphBuilder`** (`graphlint/analyzer/graph.py`) — 从解析结果构建依赖关系图，包括节点、边、连通分量分析
- **`EntryPointDetector`** (`graphlint/analyzer/entry_detect.py`) — 10 种内置入口检测规则 + 自定义规则支持
- **`WarningCollector`** (`graphlint/analyzer/warnings.py`) — 警告的收集、去重、过滤和统计
- **`ImportAnalyzer`** (`graphlint/analyzer/imports.py`) — import 语句解析与未使用 import 检测
- **`DecoratorResolver`** (`graphlint/analyzer/decorators.py`) — 装饰器解析

#### AST 解析流程

```
源文件 (.py)
    │
    ▼
AST 解析 (ast.parse)
    │
    ▼
ASTVisitor 遍历
    ├── 提取节点 (类/函数/方法/变量/字段)
    ├── 解析 import 语句
    └── 收集名称使用
    │
    ▼
GraphBuilder 构建图
    ├── 添加节点 (分配 ID)
    ├── 添加边 (read/write/call/inherit/decorate)
    ├── 入口点检测
    ├── 连通分量分析
    └── 警告收集
```

### 5. 存储/持久化层

- **`Database`** (`graphlint/storage/db.py`) — SQLite 数据库封装，支持事务
- **`Hashing`** (`graphlint/storage/hashing.py`) — 文件 SHA256 哈希计算
- **`Schema`** (`graphlint/storage/schema.py`) — 数据库表结构定义

#### 数据库表结构

| 表名 | 说明 |
|------|------|
| `files` | 文件元数据（路径、哈希、大小） |
| `nodes` | AST 节点（名称、类型、位置、文件关联） |
| `edges` | 依赖边（源/目标节点、边类型、位置） |
| `imports` | import 记录（模块路径、导入名、是否使用） |
| `warnings` | 警告信息 |
| `graph_snapshots` | 图结构快照（节点/边/警告计数、可达性标记） |

### 6. 基础设施层

- **`I18nManager`** (`graphlint/i18n/__init__.py`) — 国际化支持，提供 `zh_CN` 和 `en` 两种语言
- **`ParamDef`** (`graphlint/params.py`) — 统一参数定义，CLI 与 API 共享同一参数源
- **`Exceptions`** (`graphlint/exceptions.py`) — 自定义异常层次结构

## 数据流

### 查询流程

```
query() 调用
    │
    ▼
检查索引是否存在？ ──否──→ 自动执行 build()
    │ 是
    ▼
打开 SQLite 数据库
    │
    ├── graph_id 指定？ ──→ 查询详情 → 格式化输出
    │
    └── 列表模式
        │
        ▼
    应用过滤器 (warn_types, min_nodes, include_tests...)
        │
        ▼
    排序 (warnings/nodes/edges/name)
        │
        ▼
    输出量策略决策 (auto/summary/full/minimal)
        │
        ▼
    文本格式化 或 JSON 序列化
```

### 构建流程

```
build() 调用
    │
    ▼
扫描目录，收集 .py 文件
    │
    ├── 增量模式? ──→ 计算 SHA256 → 与缓存对比 → 仅处理变更文件
    │
    └── 强制重建? ──→ 处理所有文件
    │
    ▼
AST 解析 (并行)
    │
    ▼
GraphBuilder 构建图
    │
    ▼
入口点检测
    │
    ▼
连通分量分析
    │
    ▼
警告收集与去重
    │
    ▼
写入 SQLite 数据库
    │
    ▼
返回统计信息
```
