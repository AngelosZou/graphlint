# Entry Point Detection Reference

graphlint has 28 built-in entry point detection rules (10 for Python, 8 for Rust, 10 for C#) and supports custom rule extension. On first `graphlint build`, these rules are written as a template into `.graphlint/config.json`; thereafter the config file is the single source of truth — you may add, remove, or modify rules via `graphlint config` or by editing the file directly.

## Built-in Rules

### Python Rules

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

### Rust Rules

### 11. rust_default_bin_path

Detects Cargo's implicit binary entry paths (`src/main.rs` and `src/bin/*.rs`).

- **Match Pattern**: `file_match:src/main.rs | file_match:src/bin/*.rs`
- **Match Files**: `**/*.rs`
- **Example**:
  ```rust
  // src/main.rs — implicit Cargo binary entry
  fn main() {
      println!("Hello, world!");
  }
  ```

### 12. rust_main

Detects the Rust binary crate entry point `fn main()`.

- **Match Pattern**: `function_def:main`
- **Match Files**: `**/*.rs`
- **Example**:
  ```rust
  fn main() {
      println!("Hello, world!");
  }
  ```

### 13. rust_async_main

Detects async runtime `#[...]` attributes that decorate `main`.

- **Match Pattern**: `decorator:tokio::main | decorator:actix_rt::main | decorator:actix_web::main | decorator:async_std::main | decorator:rocket::main | decorator:rocket::launch | decorator:main`
- **Match Files**: `**/*.rs`
- **Note**: Rust attribute macros (`#[...]`) are compile-time and do **not** create `decorate` edges in the dependency graph (unlike Python decorators).
- **Example**:
  ```rust
  #[tokio::main]
  async fn main() {
      // ...
  }
  ```

### 14. rust_wasm_entry

Detects WebAssembly exports.

- **Match Pattern**: `decorator:wasm_bindgen`
- **Match Files**: `**/*.rs`
- **Example**:
  ```rust
  use wasm_bindgen::prelude::*;

  #[wasm_bindgen]
  pub fn greet(name: &str) {
      // ...
  }
  ```

### 15. rust_proc_macro

Detects Rust procedural macro entry points called by the compiler.

- **Match Pattern**: `decorator:proc_macro | decorator:proc_macro_derive | decorator:proc_macro_attribute`
- **Match Files**: `**/*.rs`
- **Example**:
  ```rust
  #[proc_macro]
  pub fn my_macro(input: TokenStream) -> TokenStream {
      // ...
  }
  ```

### 16. rust_ffi_export

Detects FFI exports via `#[no_mangle]` or `#[export_name]`.

- **Match Pattern**: `decorator:no_mangle | decorator:export_name`
- **Match Files**: `**/*.rs`
- **Example**:
  ```rust
  #[no_mangle]
  pub extern "C" fn my_export() {
      // ...
  }
  ```

### 17. rust_test

Detects Rust test files and `#[test]` functions.

- **Match Pattern**: `test_file`
- **Match Files**: `**/*.rs`
- **Note**: Test entry points do not propagate reachability to non-test code under test.
- **Example**:
  ```rust
  #[test]
  fn test_addition() {
      assert_eq!(2 + 2, 4);
  }
  ```

### 18. rust_pub_api

Treats all `pub` items in Rust library crates as entry points.

- **Match Pattern**: `visibility:pub`
- **Match Files**: `**/*.rs`
- **Note**: Disabled by default (`"enabled": false`). Use `--public-as-entry` to activate it at query time, or enable the rule in config for persistent library-crate analysis.

### C# Rules

### 19. csharp_console_app

Detects C# console application entry points: a static `Main` method or top-level statements in `Program.cs`.

- **Match Pattern**: `function_def:Main | file_is_program`
- **Match Files**: `**/Program.cs`
- **Example**:
  ```csharp
  // top-level statements
  Console.WriteLine("Hello, world!");
  ```

### 20. csharp_xunit

Detects xUnit test methods.

- **Match Pattern**: `decorator:Fact | decorator:Theory`
- **Match Files**: `**/*.cs`
- **Example**:
  ```csharp
  public class CalculatorTests
  {
      [Fact]
      public void Add_Works()
      {
          Assert.Equal(4, 2 + 2);
      }
  }
  ```

### 21. csharp_nunit

Detects NUnit test fixtures and methods.

- **Match Pattern**: `decorator:TestFixture | decorator:Test | decorator:TestCase | decorator:SetUp | decorator:OneTimeSetUp`
- **Match Files**: `**/*.cs`
- **Example**:
  ```csharp
  [TestFixture]
  public class CalculatorTests
  {
      [Test]
      public void Add_Works() { /* ... */ }
  }
  ```

### 22. csharp_mstest

Detects MSTest test classes and methods.

- **Match Pattern**: `decorator:TestClass | decorator:TestMethod | decorator:ClassInitialize | decorator:TestInitialize`
- **Match Files**: `**/*.cs`
- **Example**:
  ```csharp
  [TestClass]
  public class CalculatorTests
  {
      [TestMethod]
      public void Add_Works() { /* ... */ }
  }
  ```

### 23. csharp_webapi

Detects ASP.NET Web API controllers and action methods.

- **Match Pattern**: `decorator:ApiController | decorator:Route | decorator:HttpGet | decorator:HttpPost | decorator:HttpPut | decorator:HttpDelete | decorator:HttpPatch`
- **Match Files**: `**/*.cs`
- **Example**:
  ```csharp
  [ApiController]
  [Route("api/[controller]")]
  public class ProductsController : ControllerBase
  {
      [HttpGet]
      public IActionResult GetAll() { /* ... */ }
  }
  ```

### 24. csharp_minimal_api

Detects ASP.NET Minimal API endpoint definitions.

- **Match Pattern**: `function_call:MapGet | function_call:MapPost | function_call:MapPut | function_call:MapDelete | function_call:MapMethods`
- **Match Files**: `**/*.cs`
- **Example**:
  ```csharp
  var builder = WebApplication.CreateBuilder(args);
  var app = builder.Build();
  app.MapGet("/", () => "Hello, World!");
  app.Run();
  ```

### 25. csharp_generic_host

Detects .NET Generic Host / WebApplication startup calls.

- **Match Pattern**: `function_call:CreateDefaultBuilder | function_call:ConfigureWebHostDefaults | function_call:Run`
- **Match Files**: `**/*.cs`
- **Example**:
  ```csharp
  Host.CreateDefaultBuilder(args)
      .ConfigureServices(services => { /* ... */ })
      .Build()
      .Run();
  ```

### 26. csharp_winforms

Detects Windows Forms application entry points.

- **Match Pattern**: `function_call:Application.Run | function_call:Application.EnableVisualStyles`
- **Match Files**: `**/*.cs`
- **Example**:
  ```csharp
  Application.EnableVisualStyles();
  Application.Run(new MainForm());
  ```

### 27. csharp_wpf

Detects WPF application entry points (`App.xaml.cs`).

- **Match Pattern**: `class_definition:App`
- **Match Files**: `**/*.cs`
- **Example**:
  ```csharp
  public partial class App : Application
  {
      // Startup logic
  }
  ```

### 28. csharp_test

Detects C# test files (xUnit/NUnit/MSTest conventions).

- **Match Pattern**: `test_file`
- **Match Files**: `**/*.cs`
- **Note**: Test entry points do not propagate reachability to non-test code under test.

## `--public-as-entry` Flag

The `--public-as-entry` flag provides an alternative way to treat public items as entry points without modifying the config:

```bash
graphlint query --public-as-entry
```

This flag:
- Only applies to languages with `public` visibility declarations (Rust `pub`, C# `public`); has no effect on Python files.
- Toggles independently from the `rust_pub_api` config entry rule — the two are orthogonal mechanisms.
- **Triggers a full re-index** when switched on or off (detected via the scan stamp).
- For long-term library analysis, prefer enabling `rust_pub_api` in `.graphlint/config.json` to persist the setting and avoid repeated rebuilds.

## Custom Rules

Add custom entry detection rules via the `entry_rules` configuration.

### Unified AST Patterns

All rules (built-in and custom) use the same prefix syntax, supporting OR combinations with ` | `.

| Prefix | Description | Example | Applicable |
|--------|-------------|---------|------------|
| `function_call:<name>` | Match a function call by name | `"function_call:start_app"` | Python, C# |
| `function_def:<pattern>` | Match a function definition by name (supports glob) | `"function_def:run_*"` | Python, Rust, C# |
| `decorator:<name>` | Match a decorator (Python), attribute macro (Rust `#[...]`), or attribute (C# `[...]`) by name | `"decorator:app.route"` / `"decorator:tokio::main"` / `"decorator:Fact"` | Python, Rust, C# |
| `class_instantiation:<name>` | Match a class instantiation by name | `"class_instantiation:MyApp"` | Python |
| `class_definition:<pattern>` | Match a class/struct/record/interface definition by name (supports glob) | `"class_definition:App"` | C# |
| `file_match:<pattern>` | Match a filename pattern | `"file_match:**/startup.py"` | Python, Rust, C# |
| `file_is_program` | Match `Program.cs` with top-level statements | `"file_is_program"` | C# |
| `if_name_main` | Match `if __name__ == '__main__'` | `"if_name_main"` | Python |
| `test_file` | Match test files (uses `test_patterns` config) | `"test_file"` | Python, Rust, C# |
| `visibility:pub` | Match items with `pub` visibility modifier | `"visibility:pub"` | Rust |
| `visibility:public` | Match items with `public` visibility modifier | `"visibility:public"` | C# |
| `trait_impl:<pattern>` | Match `impl Trait for Type` blocks | `"trait_impl:Default"` | Rust |
| `macro_def:<pattern>` | Match `macro_rules!` definitions | `"macro_def:my_macro"` | Rust |

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
