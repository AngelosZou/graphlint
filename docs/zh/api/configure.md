# API 参考：configure()

`graphlint.api.configure()` 用于管理 `.graphlint/config.json` 配置。

## 函数签名

```python
def configure(
    action: str,
    key: Optional[str] = None,
    value: Optional[str] = None,
    source: Optional[str] = None,
    root_dir: str = ".",
    lang: Optional[str] = None,
    rule_json: Optional[str] = None,
    rule_name: Optional[str] = None,
    exclude_pattern: Optional[str] = None,
) -> dict
```

## 参数说明

### 通用参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action` | `str` | 是 | 配置操作类型（见下方列表） |
| `root_dir` | `str` | 否 | 项目根目录，默认 `"."` |

### 操作类型（action）

| 操作 | 说明 | 所需参数 |
|------|------|----------|
| `"show"` | 显示当前完整配置 | 无 |
| `"get"` | 获取指定配置项的值 | `key` |
| `"set"` | 设置指定配置项的值 | `key`, `value` |
| `"copy-from"` | 从其他项目目录复制配置 | `source` |
| `"add-entry-rule"` | 添加自定义入口检测规则 | `rule_json` |
| `"remove-entry-rule"` | 移除入口检测规则 | `rule_name` |
| `"add-exclude"` | 添加排除模式 | `exclude_pattern` |
| `"remove-exclude"` | 移除排除模式 | `exclude_pattern` |

### 各操作参数详情

| 参数 | 类型 | 用于操作 | 说明 |
|------|------|----------|------|
| `key` | `Optional[str]` | `get`, `set` | 配置键名 |
| `value` | `Optional[str]` | `set` | 配置值（支持类型自动转换） |
| `source` | `Optional[str]` | `copy-from` | 源配置的目录路径 |
| `rule_json` | `Optional[str]` | `add-entry-rule` | 入口规则的 JSON 字符串 |
| `rule_name` | `Optional[str]` | `remove-entry-rule` | 要移除的规则名称 |
| `exclude_pattern` | `Optional[str]` | `add-exclude`, `remove-exclude` | 排除模式字符串 |

## 返回值

所有操作均返回字典：

```python
{"status": "ok", ...}       # 成功
{"status": "error", "message": "..."}  # 失败
```

### show 操作

```python
{"status": "ok", "config": {...}}  # config 包含完整配置内容
```

### get 操作

```python
{"status": "ok", "key": "lang", "value": "zh_CN"}
```

### set 操作

```python
{"status": "ok", "message": "已设置 lang=zh_CN"}
```

值自动转换规则：
- `"true"` / `"yes"` → `True`
- `"false"` / `"no"` → `False`
- 数字字符串 → `int` / `float`
- 其他 → 保持字符串

### copy-from 操作

```python
{"status": "ok", "message": "配置已从 /path/to/project 复制"}
```

### add-entry-rule 操作

```python
{"status": "ok", "message": "入口规则已添加"}
```

`rule_json` 格式示例：
```json
{
  "name": "my_app",
  "ast_pattern": "function_call:my_entry",
  "file_pattern": "**/main.py",
  "description": "自定义入口",
  "enabled": true
}
```

### remove-entry-rule 操作

```python
{"status": "ok", "message": "入口规则 'my_app' 已移除"}
```

### add-exclude / remove-exclude 操作

```python
{"status": "ok", "message": "排除模式 'generated/' 已添加"}
```

## 示例

```python
from graphlint.api import configure

# 查看配置
result = configure(action="show")
print(result["config"])

# 获取配置项
result = configure(action="get", key="lang")
print(f"当前语言: {result['value']}")

# 设置配置项
configure(action="set", key="lang", value="en")
configure(action="set", key="performance.max_file_size_mb", value="20")

# 从其他项目复制配置
configure(action="copy-from", source="/path/to/other/project")

# 添加入口检测规则
configure(
    action="add-entry-rule",
    rule_json='{"name":"my_service","ast_pattern":"class_instantiation:MyApp","file_pattern":"**/service.py"}',
)

# 移除入口规则
configure(action="remove-entry-rule", rule_name="my_service")

# 添加排除模式
configure(action="add-exclude", exclude_pattern="generated/")

# 移除排除模式
configure(action="remove-exclude", exclude_pattern="generated/")
```

## 可用配置键

| 配置键 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `lang` | `str` | `"system"` | 界面语言：`"system"` / `"zh_CN"` / `"en"` |
| `output.default_detail` | `str` | `"auto"` | 默认详细程度 |
| `output.default_max_results` | `int` | `50` | 默认最大结果数 |
| `output.default_output_limit` | `int` | `8000` | 默认输出长度限制 |
| `performance.hash_algorithm` | `str` | `"sha256"` | 文件哈希算法 |
| `performance.max_file_size_mb` | `int` | `10` | 跳过超过此大小的文件 |
| `performance.parallel_workers` | `int` | `0` | 并行 worker 数 |
