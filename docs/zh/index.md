# graphlint 文档

**graphlint** 是一个面向 AI 生成代码场景的死代码检测工具。AI Agent 在快速生成代码时会产生大量冗余代码，污染 LLM 上下文窗口并稀释注意力。graphlint 通过 AST 解析提取代码结构，构建依赖关系图，识别入口点，找出所有不可达的死代码，让 Agent 能够自行分析和清理代码库。

## 快速链接

- [快速开始](guide/getting-started.md) — 安装与基本用法
- [Agent 集成](guide/agent-integration.md) — 将提示词安装到 Agent 工具
- [CLI 使用指南](cli/usage.md) — 命令行工具详解
- [API 参考](api/query.md) — Python API 文档
- [配置指南](guide/configuration.md) — 自定义配置说明
- [架构概览](architecture/overview.md) — 项目架构与模块说明

## 核心功能

| 功能 | 说明 |
|------|------|
| **死代码检测** | 通过图遍历找出所有入口点不可达的组件，是项目的核心目标 |
| **AST 解析** | 提取类、函数、方法、变量、字段等节点 |
| **依赖图构建** | read / write / call / inherit / decorate 五类边 |
| **入口点检测** | 10 种内置规则：main / package / fastapi / flask / django / click / typer / celery / pytest / pytest_test |
| **警告检测** | 循环引用、未使用 import、只写变量、死代码等 11 种警告 |
| **增量索引** | 基于 SHA256 哈希，仅解析变更文件 |
| **Python API + CLI** | 支持 Tool 开发集成、CI 流程，或直接供 Agent 命令行调用进行自行分析和清理 |

## 项目结构

```
graphlint/                 # 核心包
├── __init__.py           # 包入口，惰性导入公共 API
├── api.py                # Python API：query / build / configure
├── cli.py                # CLI 入口：graphlint 命令
├── params.py             # 统一参数定义（CLI 与 API 共享）
├── exceptions.py         # 自定义异常类
├── analyzer/             # 解析与分析模块
│   ├── parser.py         # AST 解析器
│   ├── graph.py          # 图构建器
│   ├── entry_detect.py   # 入口点检测
│   ├── imports.py        # import 分析
│   ├── decorators.py     # 装饰器解析
│   ├── warnings.py       # 警告收集
│   ├── _ast_visitor.py   # AST 访问器
│   ├── _graph_algo.py    # 图算法
│   └── _types.py         # 内部类型定义
├── config/               # 配置管理
│   ├── __init__.py       # 包入口
│   ├── defaults.py       # 默认配置
│   └── manager.py        # 配置管理器
├── i18n/                 # 国际化
│   ├── __init__.py       # i18n 管理器
│   ├── en.py             # 英语翻译
│   └── zh_CN.py          # 简体中文翻译
├── incremental/          # 增量索引
│   ├── indexer.py        # 增量索引器
│   └── _db_ops.py        # 数据库操作
├── query/                # 查询引擎
│   ├── engine.py         # 查询引擎
│   ├── formatter.py      # 文本格式化
│   └── volume.py         # 输出量策略
└── storage/              # 持久化
    ├── db.py             # 数据库
    ├── hashing.py        # 文件哈希
    └── schema.py         # 数据库模式
```
