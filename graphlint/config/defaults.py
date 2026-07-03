# -*- coding: utf-8 -*-
"""Default configuration values."""

from typing import Any, Dict

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": 1,
    "lang": "system",
    # -------- Entry rules --------
    "entry_rules": [
        {
            "name": "python_main",
            "file_pattern": "**/*.py",
            "ast_pattern": "if __name__ == '__main__'",
            "enabled": True,
            "description": "Standard Python __main__ entry",
        },
        {
            "name": "python_package",
            "file_pattern": "**/__init__.py",
            "ast_pattern": "file-level: all module-level nodes",
            "enabled": True,
            "description": "Package __init__.py public API entry",
        },
        {
            "name": "fastapi_app",
            "file_pattern": "**/*.py",
            "ast_pattern": "FastAPI instantiation OR uvicorn.run call",
            "enabled": True,
            "description": "FastAPI application entry",
        },
        {
            "name": "flask_app",
            "file_pattern": "**/*.py",
            "ast_pattern": "Flask instantiation OR app.run call",
            "enabled": True,
            "description": "Flask application entry",
        },
        {
            "name": "django_manage",
            "file_pattern": "**/manage.py",
            "ast_pattern": "execute_from_command_line call",
            "enabled": True,
            "description": "Django manage.py entry",
        },
        {
            "name": "click_command",
            "file_pattern": "**/*.py",
            "ast_pattern": "click.command or click.group decorator",
            "enabled": True,
            "description": "Click CLI entry",
        },
        {
            "name": "typer_app",
            "file_pattern": "**/*.py",
            "ast_pattern": "typer.Typer instantiation",
            "enabled": True,
            "description": "Typer CLI entry",
        },
        {
            "name": "celery_app",
            "file_pattern": "**/*.py",
            "ast_pattern": "celery.Celery instantiation",
            "enabled": True,
            "description": "Celery application entry",
        },
        {
            "name": "pytest_plugin",
            "file_pattern": "**/conftest.py",
            "ast_pattern": "pytest_addoption or pytest.fixture",
            "enabled": True,
            "description": "Pytest plugin/config entry",
        },
        {
            "name": "pytest_test",
            "file_pattern": "**/*.py",
            "ast_pattern": "test_* functions / Test* classes in test files",
            "enabled": True,
            "description": "Pytest test collection entry",
        },
    ],
    # -------- Test file patterns --------
    "test_patterns": {
        "file_patterns": ["test_*.py", "*_test.py"],
        "dir_patterns": ["tests/", "test/", "__tests__/"],
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
