# 异常参考

graphlint 定义的自定义异常层次结构。

## 异常层次

```
Exception
  └── GraphlintError (基类)
        ├── ConfigNotFoundError
        ├── InvalidPathError
        ├── HashMismatchError
        ├── NoIndexError
        ├── InvalidGraphIdError
        └── InvalidParamError
```

## 异常详解

### GraphlintError

所有 graphlint 异常的基类。

```python
class GraphlintError(Exception):
    def __init__(self, message: str = "") -> None
```

### ConfigNotFoundError

配置文件缺失时抛出。

```python
class ConfigNotFoundError(GraphlintError):
    def __init__(self, path: str = "") -> None
```

**触发场景**：`.graphlint/config.json` 文件不存在且无法创建默认配置。

### InvalidPathError

路径验证失败时抛出。

```python
class InvalidPathError(GraphlintError):
    def __init__(self, path: str = "", reason: str = "") -> None
```

**触发场景**：指定的 `root_dir` 目录不存在。

### HashMismatchError

文件哈希不匹配时抛出。

```python
class HashMismatchError(GraphlintError):
    def __init__(self, file_path: str = "", old_hash: str = "", new_hash: str = "") -> None
```

**触发场景**：查询时发现文件的 SHA256 哈希与缓存不一致，表明文件已被外部修改。

### NoIndexError

索引不存在时抛出。

```python
class NoIndexError(GraphlintError):
    def __init__(self, root_dir: str = "") -> None
```

**触发场景**：使用 `no_scan=True` 查询时，`.graphlint/db.sqlite` 文件不存在。

### InvalidGraphIdError

无效的图 ID 时抛出。

```python
class InvalidGraphIdError(GraphlintError):
    def __init__(self, graph_id: int = 0, max_id: int = 0) -> None
```

**触发场景**：指定的 `graph_id` 超出有效范围（1 到最大 ID）。

### InvalidParamError

参数值无效时抛出。

```python
class InvalidParamError(GraphlintError):
    def __init__(self, param_name: str = "", value: str = "", reason: str = "") -> None
```

**触发场景**：API 参数值超出有效范围，例如：
- `graph_id` ≤ 0
- `min_nodes` < 0
- `max_results` 不在 1–1000 范围内
- `output_limit` 不在 100–100000 范围内
- `path_format` 不是 `"absolute"` 或 `"relative"`
- `sort_by` 不是有效值
- `warn_types` 包含无效警告类型
- `parallel` < 0
