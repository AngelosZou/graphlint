# -*- coding: utf-8 -*-
"""Default configuration values."""

from typing import Any, Dict

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": 1,
    "lang": "system",
    # -------- Entry rules --------
    # These are the initial template written to .graphlint/config.json on
    # first run.  Once the config file exists, it is the single source of
    # truth — users may add, remove, or modify rules via `graphlint config`.
    "entry_rules": [
        {
            "name": "python_main",
            "file_pattern": "**/*.py",
            "ast_pattern": "if_name_main",
            "enabled": True,
            "description": "Standard Python __main__ entry",
        },
        {
            "name": "python_package",
            "file_pattern": "**/__init__.py",
            "ast_pattern": "file_match:**/__init__.py",
            "enabled": True,
            "description": "Package __init__.py public API entry",
        },
        {
            "name": "fastapi_app",
            "file_pattern": "**/*.py",
            "ast_pattern": "class_instantiation:FastAPI | function_call:uvicorn.run",
            "enabled": True,
            "description": "FastAPI application entry",
        },
        {
            "name": "flask_app",
            "file_pattern": "**/*.py",
            "ast_pattern": "class_instantiation:Flask | class_instantiation:flask.Flask | function_call:*.run",
            "enabled": True,
            "description": "Flask application entry",
        },
        {
            "name": "django_manage",
            "file_pattern": "**/manage.py",
            "ast_pattern": "function_call:execute_from_command_line",
            "enabled": True,
            "description": "Django manage.py entry",
        },
        {
            "name": "click_command",
            "file_pattern": "**/*.py",
            "ast_pattern": "decorator:click.command | decorator:click.group",
            "enabled": True,
            "description": "Click CLI entry",
        },
        {
            "name": "typer_app",
            "file_pattern": "**/*.py",
            "ast_pattern": "class_instantiation:typer.Typer | decorator:*.command",
            "enabled": True,
            "description": "Typer CLI entry",
        },
        {
            "name": "celery_app",
            "file_pattern": "**/*.py",
            "ast_pattern": "class_instantiation:Celery | class_instantiation:celery.Celery",
            "enabled": True,
            "description": "Celery application entry",
        },
        {
            "name": "pytest_plugin",
            "file_pattern": "**/conftest.py",
            "ast_pattern": "function_def:pytest_addoption | decorator:pytest.fixture",
            "enabled": True,
            "description": "Pytest plugin/config entry",
        },
        {
            "name": "pytest_test",
            "file_pattern": "**/*.py",
            "ast_pattern": "test_file",
            "enabled": True,
            "description": "Pytest test collection entry",
            "no_propagate": True,
        },
        {
            "name": "rust_default_bin_path",
            "file_pattern": "**/*.rs",
            "ast_pattern": "file_match:src/main.rs | file_match:src/bin/*.rs",
            "enabled": True,
            "description": "Rust default binary entry paths (src/main.rs, src/bin/*.rs)",
        },
        {
            "name": "rust_main",
            "file_pattern": "**/*.rs",
            "ast_pattern": "function_def:main",
            "enabled": True,
            "description": "Rust fn main() binary entry point",
        },
        {
            "name": "rust_async_main",
            "file_pattern": "**/*.rs",
            "ast_pattern": (
                "decorator:tokio::main | "
                "decorator:actix_rt::main | "
                "decorator:actix_web::main | "
                "decorator:async_std::main | "
                "decorator:rocket::main | "
                "decorator:rocket::launch | "
                "decorator:main"
            ),
            "enabled": True,
            "description": "Rust async runtime main attribute (tokio, actix, async-std, rocket)",
        },
        {
            "name": "rust_wasm_entry",
            "file_pattern": "**/*.rs",
            "ast_pattern": "decorator:wasm_bindgen",
            "enabled": True,
            "description": "Rust WASM exports via #[wasm_bindgen]",
        },
        {
            "name": "rust_proc_macro",
            "file_pattern": "**/*.rs",
            "ast_pattern": (
                "decorator:proc_macro | "
                "decorator:proc_macro_derive | "
                "decorator:proc_macro_attribute"
            ),
            "enabled": True,
            "description": "Rust proc macro entry points — called by the compiler",
        },
        {
            "name": "rust_ffi_export",
            "file_pattern": "**/*.rs",
            "ast_pattern": "decorator:no_mangle | decorator:export_name",
            "enabled": True,
            "description": "Rust FFI exports via #[no_mangle] / #[export_name]",
        },
        {
            "name": "rust_test",
            "file_pattern": "**/*.rs",
            "ast_pattern": "test_file",
            "enabled": True,
            "description": "Rust test files and #[test] functions",
            "no_propagate": True,
        },
        {
            "name": "rust_pub_api",
            "file_pattern": "**/*.rs",
            "ast_pattern": "visibility:pub",
            "enabled": False,
            "description": "Rust public API entry (library crate pub items)",
        },
        {
            "name": "csharp_console_app",
            "file_pattern": "**/Program.cs",
            "ast_pattern": "function_def:Main | file_is_program",
            "enabled": True,
            "description": "C# console app entry (static Main or top-level statements)",
        },
        {
            "name": "csharp_xunit",
            "file_pattern": "**/*.cs",
            "ast_pattern": "decorator:Fact | decorator:Theory",
            "enabled": True,
            "description": "C# xUnit test entry",
        },
        {
            "name": "csharp_nunit",
            "file_pattern": "**/*.cs",
            "ast_pattern": "decorator:TestFixture | decorator:Test | decorator:TestCase | decorator:SetUp | decorator:OneTimeSetUp",
            "enabled": True,
            "description": "C# NUnit test entry",
        },
        {
            "name": "csharp_mstest",
            "file_pattern": "**/*.cs",
            "ast_pattern": "decorator:TestClass | decorator:TestMethod | decorator:ClassInitialize | decorator:TestInitialize",
            "enabled": True,
            "description": "C# MSTest test entry",
        },
        {
            "name": "csharp_webapi",
            "file_pattern": "**/*.cs",
            "ast_pattern": "decorator:ApiController | decorator:Route | decorator:HttpGet | decorator:HttpPost | decorator:HttpPut | decorator:HttpDelete | decorator:HttpPatch",
            "enabled": True,
            "description": "C# ASP.NET Web API controller entry",
        },
        {
            "name": "csharp_minimal_api",
            "file_pattern": "**/*.cs",
            "ast_pattern": "function_call:MapGet | function_call:MapPost | function_call:MapPut | function_call:MapDelete | function_call:MapMethods",
            "enabled": True,
            "description": "C# ASP.NET Minimal API endpoint entry",
        },
        {
            "name": "csharp_generic_host",
            "file_pattern": "**/*.cs",
            "ast_pattern": "function_call:CreateDefaultBuilder | function_call:ConfigureWebHostDefaults | function_call:Run",
            "enabled": True,
            "description": "C# .NET Generic Host / WebApplication entry",
        },
        {
            "name": "csharp_winforms",
            "file_pattern": "**/*.cs",
            "ast_pattern": "function_call:Application.Run | function_call:Application.EnableVisualStyles",
            "enabled": True,
            "description": "C# WinForms application entry",
        },
        {
            "name": "csharp_wpf",
            "file_pattern": "**/*.cs",
            "ast_pattern": "class_definition:App",
            "enabled": True,
            "description": "C# WPF application entry (App.xaml.cs)",
        },
        {
            "name": "csharp_test",
            "file_pattern": "**/*.cs",
            "ast_pattern": "test_file",
            "enabled": True,
            "description": "C# test files (xUnit/NUnit/MSTest conventions)",
            "no_propagate": True,
        },
        {
            "name": "typescript_main",
            "file_pattern": "**/*",
            "ast_pattern": "function_def:main",
            "enabled": True,
            "description": "TypeScript/JavaScript main() function entry",
        },
        {
            "name": "typescript_index",
            "file_pattern": "**/*",
            "ast_pattern": "file_match:*/index.ts | file_match:*/index.js | file_match:*/index.tsx | file_match:*/index.mts | file_match:*/index.mjs",
            "enabled": True,
            "description": "TypeScript/JavaScript module index entry",
        },
        {
            "name": "typescript_cli",
            "file_pattern": "**/*",
            "ast_pattern": "function_call:app.listen | function_call:server.listen | function_call:express | class_instantiation:Express | class_instantiation:Koa",
            "enabled": True,
            "description": "TypeScript CLI/server listen entry",
        },
        {
            "name": "typescript_nextjs",
            "file_pattern": "**/pages/**",
            "ast_pattern": "file_match:**/pages/**",
            "enabled": True,
            "description": "Next.js pages router entry",
        },
        {
            "name": "typescript_nestjs",
            "file_pattern": "**/*",
            "ast_pattern": "decorator:Module | decorator:Controller | decorator:Injectable",
            "enabled": True,
            "description": "NestJS entry (Module/Controller/Injectable)",
        },
        {
            "name": "typescript_react_component",
            "file_pattern": "**/*",
            "ast_pattern": "jsx_element:*",
            "enabled": True,
            "description": "React component JSX entry",
        },
        {
            "name": "typescript_test",
            "file_pattern": "**/*",
            "ast_pattern": "test_file",
            "enabled": True,
            "description": "TypeScript test files (Jest/Vitest/Mocha conventions)",
            "no_propagate": True,
        },
    ],
    # -------- Test file patterns --------
    "test_patterns": {
        "file_patterns": ["test_*.py", "*_test.py", "test_*.rs", "*_test.rs",
                          "*Tests.cs", "*Test.cs", "*.Tests.cs"],
        "dir_patterns": ["tests/", "test/", "__tests__/", "Tests/", "Test/"],
        "config_files": ["conftest.py"],
        "function_patterns": ["test_*"],
    },
    # -------- Exclude patterns --------
    "exclude_patterns": {
        "always_exclude": [
            "__pycache__/",
            ".mypy_cache/",
            ".pytest_cache/",
            ".tox/",
            ".venv/",
            "venv/",
            "env/",
            "virtualenv/",
            ".env/",
            "node_modules/",
            ".git/",
            ".svn/",
            ".hg/",
            ".idea/",
            ".vscode/",
            ".vs/",
            ".graphlint/",
            "build/",
            "dist/",
            "target/",
            ".cargo/",
            "*.egg-info/",
            "*.pyc",
            "*.pyo",
        ],
        "user_exclude": [],
    },
    # -------- Performance --------
    "performance": {
        "parallel_workers": 0,
        "hash_algorithm": "sha256",
        "max_file_size_mb": 10,
    },
    # -------- Output --------
    "output": {
        "default_detail": "auto",
        "default_max_results": 50,
        "default_output_limit": 8000,
    },
}
