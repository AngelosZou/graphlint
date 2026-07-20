# 入口点检测参考

graphlint 内置 10 种入口点检测规则，并支持自定义规则扩展。

## 内置规则

### 1. python_main

检测标准的 Python 入口点 `if __name__ == '__main__':`。

- **匹配模式**：`ast.If` 节点，条件为 `__name__ == '__main__'`
- **匹配文件**：`**/*.py`
- **示例**：
  ```python
  if __name__ == '__main__':
      main()
  ```

### 2. fastapi_app

检测 FastAPI 应用的入口点。

- **匹配模式**：
  - `FastAPI()` 类的实例化
  - `uvicorn.run()` 或 `uvicorn.run()` 调用
- **匹配文件**：`**/*.py`
- **示例**：
  ```python
  from fastapi import FastAPI
  import uvicorn

  app = FastAPI()

  if __name__ == '__main__':
      uvicorn.run(app)
  ```

### 3. flask_app

检测 Flask 应用的入口点。

- **匹配模式**：
  - `Flask()` 或 `flask.Flask()` 类的实例化
  - 任何 `.run()` 方法调用
- **匹配文件**：`**/*.py`
- **示例**：
  ```python
  from flask import Flask

  app = Flask(__name__)
  app.run()
  ```

### 4. django_manage

检测 Django 项目的入口点。

- **匹配模式**：`execute_from_command_line()` 调用
- **匹配文件**：`**/manage.py`
- **示例**：
  ```python
  # manage.py
  from django.core.management import execute_from_command_line
  execute_from_command_line(sys.argv)
  ```

### 5. click_command

检测 Click CLI 命令的入口点。

- **匹配模式**：`@click.command` 或 `@click.group` 装饰器
- **匹配文件**：`**/*.py`
- **示例**：
  ```python
  import click

  @click.command()
  def hello():
      click.echo("Hello!")

  @click.group()
  def cli():
      pass
  ```

### 6. typer_app

检测 Typer CLI 应用的入口点。

- **匹配模式**：
  - `typer.Typer()` 类的实例化
  - 任何 `.command` 装饰器
- **匹配文件**：`**/*.py`
- **示例**：
  ```python
  import typer

  app = typer.Typer()

  @app.command()
  def hello():
      typer.echo("Hello!")
  ```

### 7. celery_app

检测 Celery 异步任务应用的入口点。

- **匹配模式**：`Celery()` 或 `celery.Celery()` 类的实例化
- **匹配文件**：`**/*.py`
- **示例**：
  ```python
  from celery import Celery

  app = Celery('tasks', broker='redis://localhost')
  ```

### 8. python_package

检测 Python 包入口点（`__init__.py` 文件）。

- **匹配模式**：文件名为 `__init__.py`
- **匹配文件**：`**/__init__.py`
- **示例**：
  ```python
  # mypackage/__init__.py
  from .submodule import useful_function
  ```

### 9. pytest_plugin

检测 Pytest 插件/配置的入口点。

- **匹配模式**：
  - `pytest_addoption` 函数定义
  - `@pytest.fixture` 装饰器
- **匹配文件**：`**/conftest.py`
- **示例**：
  ```python
  import pytest

  def pytest_addoption(parser):
      parser.addoption("--my-option")

  @pytest.fixture
  def my_fixture():
      return 42
  ```

### 10. pytest_test

检测 Pytest 测试用例作为入口点。

- **匹配模式**：
  - 测试文件（`test_*.py` / `*_test.py`）或测试目录下的文件
  - 包含 `test_*` 函数或 `Test*` 类
- **匹配文件**：`**/*.py`
- **注意**：测试入口点不会将可达性传播到被测试的非测试代码
- **示例**：
  ```python
  # tests/test_example.py
  def test_hello():
      assert 1 + 1 == 2

  class TestCalculator:
      def test_add(self):
          pass
  ```

## 自定义规则

通过 `entry_rules` 配置添加自定义入口检测规则。

### 统一 AST 模式

所有规则（内置和自定义）使用相同的前缀语法，支持 ` | ` 分隔的 OR 组合。

| 前缀 | 说明 | 示例 |
|------|------|------|
| `function_call:<name>` | 匹配指定名称的函数调用 | `"function_call:start_app"` |
| `function_def:<pattern>` | 匹配指定名称的函数定义（支持 glob） | `"function_def:run_*"` |
| `decorator:<name>` | 匹配指定名称的装饰器 | `"decorator:app.route"` |
| `class_instantiation:<name>` | 匹配指定名称的类实例化 | `"class_instantiation:MyApp"` |
| `file_match:<pattern>` | 匹配文件名模式 | `"file_match:**/startup.py"` |
| `if_name_main` | 匹配 `if __name__ == '__main__'` | `"if_name_main"` |
| `test_file` | 匹配测试文件（使用 `test_patterns` 配置） | `"test_file"` |

### 自定义规则示例

```json
{
  "name": "my_service",
  "ast_pattern": "class_instantiation:FastAPI",
  "file_pattern": "**/service.py",
  "description": "FastAPI service entry",
  "enabled": true
}
```

```json
{
  "name": "custom_cli",
  "ast_pattern": "function_call:main_cli",
  "file_pattern": "**/entry.py",
  "description": "Custom CLI entry",
  "enabled": true
}
```

## 入口点与死代码检测

入口点检测与死代码分析紧密相关：

1. 检测所有入口点（内置规则 + 自定义规则）
2. 构建依赖图并计算连通分量
3. 标记包含入口点的连通分量为"活跃"
4. 没有入口点的连通分量被标记为"死代码"
