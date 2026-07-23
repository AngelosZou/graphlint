# 入口点检测参考

graphlint 内置 17 种入口点检测规则（Python 10 种、Rust 7 种），并支持自定义规则扩展。首次运行 `graphlint build` 时，这些规则作为模板写入 `.graphlint/config.json` 中，此后配置文件即为唯一入口规则来源——你可以通过 `graphlint config` 命令或直接编辑配置文件来添加、删除或修改规则。

## 内置规则

### Python 规则

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

### Rust 规则

### 11. rust_main

检测 Rust 二进制 crate 入口点 `fn main()`。

- **匹配模式**：`function_def:main`
- **匹配文件**：`**/*.rs`
- **示例**：
  ```rust
  fn main() {
      println!("Hello, world!");
  }
  ```

### 12. rust_async_main

检测异步运行时 `#[...]` 属性宏装饰的 `main` 函数。

- **匹配模式**：`decorator:tokio::main | decorator:actix_rt::main | decorator:actix_web::main | decorator:async_std::main | decorator:rocket::main | decorator:rocket::launch | decorator:main`
- **匹配文件**：`**/*.rs`
- **注意**：Rust 属性宏（`#[...]`）是编译时的，在依赖图中**不**产生 `decorate` 边（与 Python 装饰器不同）。
- **示例**：
  ```rust
  #[tokio::main]
  async fn main() {
      // ...
  }
  ```

### 13. rust_wasm_entry

检测 WebAssembly 导出。

- **匹配模式**：`decorator:wasm_bindgen`
- **匹配文件**：`**/*.rs`
- **示例**：
  ```rust
  use wasm_bindgen::prelude::*;

  #[wasm_bindgen]
  pub fn greet(name: &str) {
      // ...
  }
  ```

### 14. rust_proc_macro

检测 Rust 过程宏入口点（由编译器调用）。

- **匹配模式**：`decorator:proc_macro | decorator:proc_macro_derive | decorator:proc_macro_attribute`
- **匹配文件**：`**/*.rs`
- **示例**：
  ```rust
  #[proc_macro]
  pub fn my_macro(input: TokenStream) -> TokenStream {
      // ...
  }
  ```

### 15. rust_ffi_export

检测 FFI 导出（`#[no_mangle]` 或 `#[export_name]`）。

- **匹配模式**：`decorator:no_mangle | decorator:export_name`
- **匹配文件**：`**/*.rs`
- **示例**：
  ```rust
  #[no_mangle]
  pub extern "C" fn my_export() {
      // ...
  }
  ```

### 16. rust_test

检测 Rust 测试文件和 `#[test]` 函数。

- **匹配模式**：`test_file`
- **匹配文件**：`**/*.rs`
- **注意**：测试入口点不会将可达性传播到被测试的非测试代码。
- **示例**：
  ```rust
  #[test]
  fn test_addition() {
      assert_eq!(2 + 2, 4);
  }
  ```

### 17. rust_pub_api

将 Rust 库 crate 中所有 `pub` 项目视为入口点。

- **匹配模式**：`visibility:pub`
- **匹配文件**：`**/*.rs`
- **注意**：默认禁用（`"enabled": false`）。使用 `--public-as-entry` 在查询时激活，或在配置中启用该规则以实现持久的库代码分析。

## `--public-as-entry` 标志

`--public-as-entry` 标志提供了一种无需修改配置文件即可将公开项视为入口点的方式：

```bash
graphlint query --public-as-entry
```

此标志：
- 仅适用于具有 `public` 可见性声明的语言（Rust `pub`），对 Python 文件无效。
- 与 `rust_pub_api` 配置入口规则独立——两者是正交的机制。
- **开关时会触发全量重新索引**（通过扫描戳检测变化）。
- 对于长期库代码分析，建议在 `.graphlint/config.json` 中启用 `rust_pub_api` 以持久化设置，避免重复构建。

## 自定义规则

通过 `entry_rules` 配置添加自定义入口检测规则。

### 统一 AST 模式

所有规则（内置和自定义）使用相同的前缀语法，支持 ` | ` 分隔的 OR 组合。

| 前缀 | 说明 | 示例 | 适用语言 |
|------|------|------|----------|
| `function_call:<name>` | 匹配指定名称的函数调用 | `"function_call:start_app"` | Python |
| `function_def:<pattern>` | 匹配指定名称的函数定义（支持 glob） | `"function_def:run_*"` | Python、Rust |
| `decorator:<name>` | 匹配装饰器（Python）或属性宏（Rust `#[...]`） | `"decorator:app.route"` / `"decorator:tokio::main"` | Python、Rust |
| `class_instantiation:<name>` | 匹配指定名称的类实例化 | `"class_instantiation:MyApp"` | Python |
| `file_match:<pattern>` | 匹配文件名模式 | `"file_match:**/startup.py"` | Python、Rust |
| `if_name_main` | 匹配 `if __name__ == '__main__'` | `"if_name_main"` | Python |
| `test_file` | 匹配测试文件（使用 `test_patterns` 配置） | `"test_file"` | Python、Rust |
| `visibility:pub` | 匹配具有 `pub` 可见性修饰符的项目 | `"visibility:pub"` | Rust |
| `trait_impl:<pattern>` | 匹配 `impl Trait for Type` 实现块 | `"trait_impl:Default"` | Rust |
| `macro_def:<pattern>` | 匹配 `macro_rules!` 定义 | `"macro_def:my_macro"` | Rust |

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
