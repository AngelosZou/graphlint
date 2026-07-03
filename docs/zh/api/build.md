# API 参考：build()

`graphlint.api.build()` 用于构建或重建依赖图索引。

## 函数签名

```python
def build(
    force_rebuild: bool = False,
    parallel: int = 0,
    root_dir: str = ".",
    lang: str = "system",
) -> dict
```

## 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `force_rebuild` | `bool` | `False` | 强制全量重建（忽略 SHA256 增量缓存） |
| `parallel` | `int` | `0` | 并行 worker 数（0=自动检测 CPU 核心数，最大 64） |
| `root_dir` | `str` | `"."` | 项目根目录路径 |
| `lang` | `str` | `"system"` | 界面语言：`"system"` / `"zh_CN"` / `"en"` |

## 返回值

返回字典，包含构建统计信息：

```python
{
    "status": "ok",              # "ok" 表示成功
    "files_scanned": 150,        # 扫描的文件总数
    "files_changed": 12,         # 内容发生变更的文件数
    "files_added": 3,            # 新增的文件数
    "files_removed": 1,          # 被删除的文件数
    "nodes_added": 45,           # 新增的 AST 节点数
    "edges_updated": 120,        # 更新/新增的边数
    "duration_ms": 320,          # 构建耗时（毫秒）
    "warnings_generated": 8,     # 生成的警告数
}
```

## 增量索引机制

`build()` 默认使用增量索引，流程如下：

1. **扫描文件**：遍历项目目录，收集所有 `.py` 文件
2. **计算哈希**：对每个文件计算 SHA256 哈希值
3. **比较缓存**：与 `.graphlint/` 缓存中的哈希值对比
4. **仅解析变更**：只对哈希变化的文件执行 AST 解析
5. **更新图结构**：合并新旧数据，更新依赖图
6. **收集警告**：检测循环引用、未使用 import 等问题

当 `force_rebuild=True` 时，跳过步骤 2-4，直接全量重建。

## 并行构建

`parallel` 参数控制构建时的并行度：

- `0`（默认）：自动检测 CPU 核心数
- `N > 0`：使用 N 个 worker
- 最大值限制为 64

并行构建通过 `concurrent.futures.ProcessPoolExecutor` 实现，每个 worker 独立解析文件。

## 示例

```python
from graphlint.api import build

# 增量构建
result = build()
print(f"扫描 {result['files_scanned']} 个文件，新增 {result['nodes_added']} 个节点")

# 强制全量重建
result = build(force_rebuild=True)
print(f"耗时: {result['duration_ms']}ms")

# 并行构建
result = build(parallel=4)

# 指定项目目录
result = build(root_dir="/path/to/project")

# 自动检测 CPU 核心数的并行构建
result = build(parallel=0)
```

## 异常

| 异常 | 触发条件 |
|------|----------|
| `InvalidParamError` | `parallel` 参数小于 0 |
| `InvalidPathError` | 指定的 root_dir 不存在 |
