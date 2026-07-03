# 警告类型参考

graphlint 支持 11 种代码分析警告类型。

## 警告类型一览

| 警告类型 | 严重级别 | 说明 |
|----------|----------|------|
| `unused_import` | `warning` | 导入了但未使用的模块或名称 |
| `dynamic_import` | `warning` | 动态 import（如 `__import__()` 或 `importlib.import_module()`） |
| `circular_ref` | `warning` | 模块或组件间的循环引用 |
| `syntax_error` | `error` | 文件存在语法错误，无法解析 |
| `write_only` | `warning` | 变量被赋值但从未被读取 |
| `deprecated_usage` | `warning` | 使用了已弃用的 API |
| `dead_code` | `info` | 无法从任何入口点到达的代码（死代码） |
| `type_mismatch` | `warning` | 类型注解与字面量值的类型冲突 |
| `unresolved_ref` | `warning` | 引用了未解析的符号 |
| `unused_variable` | `warning` | 定义了但从未使用的变量 |
| `file_too_large` | `info` | 文件超过大小限制，已被跳过 |

## 各类型详解

### unused_import — 未使用的导入

检测未使用的 import 语句。分析器会收集文件中所有已使用的名称，然后与 import 导入的名称进行对比。

**示例**：
```python
import os        # 如果 os 在后续代码中未被使用 → 警告
import sys       # 如果 sys 被使用 → 正常
```

### dynamic_import — 动态导入

检测使用 `__import__()` 或 `importlib.import_module()` 进行的动态导入。如果导入的模块名是动态构建的（如 f-string 或字符串拼接），则标记为动态导入。

**示例**：
```python
module = __import__(f"plugin_{name}")       # 动态导入 → 警告
lib = importlib.import_module("json")       # 绝对导入 → 正常
```

### circular_ref — 循环引用

通过图算法检测组件间的循环依赖关系。当两个或多个组件之间存在相互引用时触发。

### syntax_error — 语法错误

文件无法通过 `ast.parse()` 解析时触发。通常意味着文件包含 Python 语法错误。

### write_only — 只写变量

变量被赋值但从未被读取。分析器会检查每个变量/字段节点是否存在 READ 边。

**示例**：
```python
x = 10      # 赋值为 10
x = 20      # 重新赋值，但 x 从未被读取 → 警告
```

### deprecated_usage — 已弃用的 API

检测使用了 `@deprecated` 装饰器标记的已弃用函数或类。

### dead_code — 死代码

无法从任何入口点到达的组件（连通分量）。当某个连通分量中没有节点被标记为入口点时触发。

### type_mismatch — 类型不匹配

类型注解与字面量值的类型不一致。

**示例**：
```python
count: int = "hello"    # 类型注解为 int，但赋值为字符串 → 警告
```

### unresolved_ref — 未解析的引用

在符号索引中无法找到的引用。

### unused_variable — 未使用的变量

定义了但从未被读取也从未被写入的变量。

**示例**：
```python
def func():
    x = 10      # 定义了但从未使用 → 警告
    return
```

### file_too_large — 文件过大

文件大小超过 `performance.max_file_size_mb` 配置值（默认 10MB），被跳过不进行 AST 解析。

## 过滤警告

### CLI 方式

```bash
# 仅显示循环引用警告
graphlint query --warn-types "circular_ref"

# 显示多种警告
graphlint query --warn-types "circular_ref,unused_import"
```

### API 方式

```python
from graphlint.api import query

# 仅显示循环引用
result = query(warn_types="circular_ref", json_output=True)

# 排除干净的图
result = query(exclude_clean=True)
```
