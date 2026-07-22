# Entry Point Detection Reference

graphlint has 10 built-in entry point detection rules and supports custom rule extension. On first `graphlint build`, these rules are written as a template into `.graphlint/config.json`; thereafter the config file is the single source of truth — you may add, remove, or modify rules via `graphlint config` or by editing the file directly.

## Built-in Rules

### 1. python_main

Detects the standard Python entry point `if __name__ == '__main__':`.

- **Match Pattern**: `ast.If` node with condition `__name__ == '__main__'`
- **Match Files**: `**/*.py`
- **Example**:
  ```python
  if __name__ == '__main__':
      main()
  ```

### 2. fastapi_app

Detects FastAPI application entry points.

- **Match Pattern**:
  - `FastAPI()` class instantiation
  - `uvicorn.run()` call
- **Match Files**: `**/*.py`
- **Example**:
  ```python
  from fastapi import FastAPI
  import uvicorn

  app = FastAPI()

  if __name__ == '__main__':
      uvicorn.run(app)
  ```

### 3. flask_app

Detects Flask application entry points.

- **Match Pattern**:
  - `Flask()` or `flask.Flask()` class instantiation
  - Any `.run()` method call
- **Match Files**: `**/*.py`
- **Example**:
  ```python
  from flask import Flask

  app = Flask(__name__)
  app.run()
  ```

### 4. django_manage

Detects Django project entry points.

- **Match Pattern**: `execute_from_command_line()` call
- **Match Files**: `**/manage.py`
- **Example**:
  ```python
  # manage.py
  from django.core.management import execute_from_command_line
  execute_from_command_line(sys.argv)
  ```

### 5. click_command

Detects Click CLI command entry points.

- **Match Pattern**: `@click.command` or `@click.group` decorator
- **Match Files**: `**/*.py`
- **Example**:
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

Detects Typer CLI application entry points.

- **Match Pattern**:
  - `typer.Typer()` class instantiation
  - Any `.command` decorator
- **Match Files**: `**/*.py`
- **Example**:
  ```python
  import typer

  app = typer.Typer()

  @app.command()
  def hello():
      typer.echo("Hello!")
  ```

### 7. celery_app

Detects Celery async task application entry points.

- **Match Pattern**: `Celery()` or `celery.Celery()` class instantiation
- **Match Files**: `**/*.py`
- **Example**:
  ```python
  from celery import Celery

  app = Celery('tasks', broker='redis://localhost')
  ```

### 8. python_package

Detects Python package entry points (`__init__.py` files).

- **Match Pattern**: Filename is `__init__.py`
- **Match Files**: `**/__init__.py`
- **Example**:
  ```python
  # mypackage/__init__.py
  from .submodule import useful_function
  ```

### 9. pytest_plugin

Detects Pytest plugin/configuration entry points.

- **Match Pattern**:
  - `pytest_addoption` function definition
  - `@pytest.fixture` decorator
- **Match Files**: `**/conftest.py`
- **Example**:
  ```python
  import pytest

  def pytest_addoption(parser):
      parser.addoption("--my-option")

  @pytest.fixture
  def my_fixture():
      return 42
  ```

### 10. pytest_test

Detects Pytest test cases as entry points.

- **Match Pattern**:
  - Test files (`test_*.py` / `*_test.py`) or files in test directories
  - Contains `test_*` functions or `Test*` classes
- **Match Files**: `**/*.py`
- **Note**: Test entry points do not propagate reachability to non-test code under test
- **Example**:
  ```python
  # tests/test_example.py
  def test_hello():
      assert 1 + 1 == 2

  class TestCalculator:
      def test_add(self):
          pass
  ```

## Custom Rules

Add custom entry detection rules via the `entry_rules` configuration.

### Unified AST Patterns

All rules (built-in and custom) use the same prefix syntax, supporting OR combinations with ` | `.

| Prefix | Description | Example |
|--------|-------------|---------|
| `function_call:<name>` | Match a function call by name | `"function_call:start_app"` |
| `function_def:<pattern>` | Match a function definition by name (supports glob) | `"function_def:run_*"` |
| `decorator:<name>` | Match a decorator by name | `"decorator:app.route"` |
| `class_instantiation:<name>` | Match a class instantiation by name | `"class_instantiation:MyApp"` |
| `file_match:<pattern>` | Match a filename pattern | `"file_match:**/startup.py"` |
| `if_name_main` | Match `if __name__ == '__main__'` | `"if_name_main"` |
| `test_file` | Match test files (uses `test_patterns` config) | `"test_file"` |

### Custom Rule Examples

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

## Entry Points and Dead Code Detection

Entry point detection is closely tied to dead code analysis:

1. Detect all entry points (built-in rules + custom rules)
2. Build the dependency graph and compute connected components
3. Mark connected components containing entry points as "active"
4. Connected components without entry points are marked as "dead code"
