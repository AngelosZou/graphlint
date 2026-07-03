# API 参考：query()

`graphlint.api.query()` 用于查询代码依赖关系图。

## 函数签名

```python
def query(
    include_tests: bool = False,
    exclude_clean: bool = False,
    exclude_unreachable: bool = False,
    dead_code_tests: bool = False,
    graph_id: Optional[int] = None,
    json_output: bool = False,
    path_format: str = "relative",
    root_dir: str = ".",
    max_results: int = 50,
    min_nodes: int = 0,
    max_nodes: Optional[int] = None,
    warn_types: Optional[str] = None,
    sort_by: str = "warnings",
    detail_level: str = "auto",
    output_limit: int = 8000,
    edge_limit: int = 10,
    file_limit: int = 10,
    node_limit: int = 30,
    no_scan: bool = False,
    lang: str = "system",
) -> Union[str, dict]
```

## 参数说明

### 筛选参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `include_tests` | `bool` | `False` | 包含测试文件中的节点 |
| `exclude_clean` | `bool` | `False` | 排除无异常的图（仅显示有警告/错误的图） |
| `exclude_unreachable` | `bool` | `False` | 仅返回从入口经 CALL 边可达的图（排除不可达死代码） |
| `dead_code_tests` | `bool` | `False` | 查询引用已死代码的测试文件 |
| `graph_id` | `Optional[int]` | `None` | 查询指定图的详细信息 |
| `min_nodes` | `int` | `0` | 只返回节点数 ≥ N 的图 |
| `max_nodes` | `Optional[int]` | `None` | 只返回节点数 ≤ N 的图 |
| `warn_types` | `Optional[str]` | `None` | 逗号分隔的警告类型过滤 |

### 输出参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `json_output` | `bool` | `False` | 以结构化 JSON 格式输出 |
| `path_format` | `str` | `"relative"` | 路径格式：`"absolute"` / `"relative"` |
| `max_results` | `int` | `50` | 最大返回图数量（1–1000） |
| `sort_by` | `str` | `"warnings"` | 排序方式：`"warnings"` / `"nodes"` / `"edges"` / `"name"` |
| `detail_level` | `str` | `"auto"` | 详细程度：`"auto"` / `"summary"` / `"full"` / `"minimal"` |
| `output_limit` | `int` | `8000` | 输出文本长度限制（字符，100–100000） |
| `edge_limit` | `int` | `10` | 单图详情最大显示的边数（0=不限制） |
| `file_limit` | `int` | `10` | 单图详情最大显示的文件数（0=不限制） |
| `node_limit` | `int` | `30` | 单图详情最大显示的节点数（0=不限制） |

### 行为参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `root_dir` | `str` | `"."` | 指定目标项目根目录 |
| `no_scan` | `bool` | `False` | 跳过自动扫描/构建，直接查询已有索引 |
| `lang` | `str` | `"system"` | 界面语言：`"system"` / `"zh_CN"` / `"en"` |

## 返回值

### 文本模式（`json_output=False`，默认）

返回格式化的字符串，包含图列表或详细信息。

### JSON 模式（`json_output=True`）

返回字典，结构如下：

```json
{
  "status": "ok",
  "query_time_ms": 150,
  "total_graphs": 5,
  "returned": 5,
  "root_dir": "/path/to/project",
  "graphs": [
    {
      "graph_id": 1,
      "name": "module_name",
      "nodes_count": 12,
      "edges_count": 25,
      "entry_count": 2,
      "warnings": 3,
      "warnings_detail": [
        {"type": "circular_ref", "severity": "warning", "message": "...", "file": "..."}
      ]
    }
  ]
}
```

查询详细信息时（指定 `graph_id`）：

```json
{
  "status": "ok",
  "query_time_ms": 25,
  "graph_id": 1,
  "name": "module_name",
  "nodes": [
    {"id": 1, "name": "MyClass", "type": "class", "line": 10, "file": "src/module.py"}
  ],
  "edges": [
    {"source": 1, "target": 2, "type": "call", "line": 15}
  ],
  "warnings": [...]
}
```

## 示例

```python
from graphlint.api import query

# 基本查询
result = query()

# JSON 输出，按警告数排序
result = query(
    include_tests=True,
    json_output=True,
    max_results=20,
    sort_by="warnings",
)

# 查询特定图详情
detail = query(graph_id=1, detail_level="full", json_output=True)

# 查询死代码测试引用
dead = query(dead_code_tests=True, json_output=True)

# 仅查循环引用警告
circ = query(warn_types="circular_ref", json_output=True)

# 最小化输出
minimal = query(detail_level="minimal", max_results=5)
```

## 异常

| 异常 | 触发条件 |
|------|----------|
| `InvalidParamError` | 参数值超出有效范围 |
| `InvalidPathError` | 指定的 root_dir 不存在 |
| `NoIndexError` | 未构建索引且 `no_scan=True` |
| `InvalidGraphIdError` | 指定的 graph_id 不存在 |
| `HashMismatchError` | 文件哈希变化导致缓存失效 |
