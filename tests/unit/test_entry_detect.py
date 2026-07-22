# -*- coding: utf-8 -*-
"""Entry point detector tests."""

import pytest

from graphlint.analyzer._types import NodeInfo, ParseResult
from graphlint.analyzer.language.python.entry import EntryPointDetector


def _make_node(nid, name, node_type="function", line=1, is_entry=False):
    """Helper to create NodeInfo."""
    return NodeInfo(
        id=nid,
        name=name,
        qualified_name=f"mod.{name}",
        node_type=node_type,
        line_start=line,
        line_end=line + 2,
        col_offset=0,
    )


def _make_result(file_path, nodes, imports=None, name_usages=None, warnings=None,
                 source=None):
    """Helper to create ParseResult."""
    return ParseResult(
        file_path=file_path,
        nodes=nodes,
        imports=imports or [],
        name_usages=name_usages or set(),
        warnings=warnings or [],
        hash="abc123",
        source=source,
    )


DEFAULT_RULES = [
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
]


@pytest.mark.timeout(30)
class TestEntryPointDetector:
    """EntryPointDetector black-box tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.detector = EntryPointDetector(DEFAULT_RULES)

    def test_main_entry(self):
        """File with if __name__ == '__main__' detected as entry."""
        source = "if __name__ == '__main__':\n    main()\n"
        node = _make_node(1, "main", node_type="function")
        result = _make_result("main.py", [node], source=source)
        entries = self.detector.detect(
            {"main.py": result},
            [node],
            {1: node},
        )
        main_entries = [e for e in entries if e.rule_name == "python_main"]
        assert len(main_entries) == 1
        assert main_entries[0].description == "Standard Python __main__ entry"

    def test_main_entry_no_match(self):
        """File without __main__ check returns empty."""
        source = "x = 1\n"
        node = _make_node(1, "x", node_type="variable")
        result = _make_result("other.py", [node], source=source)
        entries = self.detector.detect(
            {"other.py": result},
            [node],
            {1: node},
        )
        main_entries = [e for e in entries if e.rule_name == "python_main"]
        assert len(main_entries) == 0

    def test_package_entry(self):
        """__init__.py detected as package API entry point."""
        node = _make_node(1, "__version__", node_type="variable")
        result = _make_result("mypkg/__init__.py", [node])
        entries = self.detector.detect(
            {"mypkg/__init__.py": result},
            [node],
            {1: node},
        )
        pkg_entries = [e for e in entries if e.rule_name == "python_package"]
        assert len(pkg_entries) == 1

    def test_package_entry_not_init(self):
        """Non __init__.py not matched by python_package."""
        node = _make_node(1, "foo", node_type="function")
        result = _make_result("mypkg/module.py", [node])
        entries = self.detector.detect(
            {"mypkg/module.py": result},
            [node],
            {1: node},
        )
        pkg_entries = [e for e in entries if e.rule_name == "python_package"]
        assert len(pkg_entries) == 0

    def test_fastapi_entry_instantiation(self):
        """FastAPI() instantiation detected as entry."""
        source = "from fastapi import FastAPI\napp = FastAPI()\n"
        node = _make_node(1, "app", node_type="variable")
        result = _make_result("app.py", [node], source=source)
        entries = self.detector.detect({"app.py": result}, [node], {1: node})
        fastapi_entries = [e for e in entries if e.rule_name == "fastapi_app"]
        assert len(fastapi_entries) == 1

    def test_fastapi_entry_uvicorn(self):
        """uvicorn.run() call detected as entry."""
        source = "import uvicorn\nuvicorn.run('app:app')\n"
        node = _make_node(1, "main", node_type="function")
        result = _make_result("main.py", [node], source=source)
        entries = self.detector.detect({"main.py": result}, [node], {1: node})
        fastapi_entries = [e for e in entries if e.rule_name == "fastapi_app"]
        assert len(fastapi_entries) == 1

    def test_flask_entry_instantiation(self):
        """Flask() instantiation detected as entry."""
        source = "from flask import Flask\napp = Flask(__name__)\n"
        node = _make_node(1, "app", node_type="variable")
        result = _make_result("flask_app.py", [node], source=source)
        entries = self.detector.detect({"flask_app.py": result}, [node], {1: node})
        flask_entries = [e for e in entries if e.rule_name == "flask_app"]
        assert len(flask_entries) == 1

    def test_flask_entry_run(self):
        """app.run() call detected as entry."""
        source = "app.run()\n"
        node = _make_node(1, "main", node_type="function")
        result = _make_result("flask_app.py", [node], source=source)
        entries = self.detector.detect({"flask_app.py": result}, [node], {1: node})
        flask_entries = [e for e in entries if e.rule_name == "flask_app"]
        assert len(flask_entries) == 1

    def test_django_entry(self):
        """manage.py with execute_from_command_line detected."""
        source = (
            "from django.core.management import execute_from_command_line\n"
            "execute_from_command_line()\n"
        )
        node = _make_node(1, "main", node_type="function")
        result = _make_result("manage.py", [node], source=source)
        entries = self.detector.detect({"manage.py": result}, [node], {1: node})
        django_entries = [e for e in entries if e.rule_name == "django_manage"]
        assert len(django_entries) == 1

    def test_django_entry_wrong_file(self):
        """Non-manage.py not matched by django_manage."""
        source = "execute_from_command_line()\n"
        node = _make_node(1, "main", node_type="function")
        result = _make_result("other.py", [node], source=source)
        entries = self.detector.detect({"other.py": result}, [node], {1: node})
        django_entries = [e for e in entries if e.rule_name == "django_manage"]
        assert len(django_entries) == 0

    def test_click_entry(self):
        """@click.command decorator detected."""
        source = (
            "import click\n"
            "@click.command()\n"
            "def cli():\n"
            "    pass\n"
        )
        node = _make_node(1, "cli", node_type="function")
        result = _make_result("cli.py", [node], source=source)
        entries = self.detector.detect({"cli.py": result}, [node], {1: node})
        click_entries = [e for e in entries if e.rule_name == "click_command"]
        assert len(click_entries) == 1

    def test_click_group_entry(self):
        """@click.group decorator detected."""
        source = (
            "import click\n"
            "@click.group()\n"
            "def cli():\n"
            "    pass\n"
        )
        node = _make_node(1, "cli", node_type="function")
        result = _make_result("cli.py", [node], source=source)
        entries = self.detector.detect({"cli.py": result}, [node], {1: node})
        click_entries = [e for e in entries if e.rule_name == "click_command"]
        assert len(click_entries) == 1

    def test_typer_entry(self):
        """typer.Typer() detected."""
        source = "import typer\napp = typer.Typer()\n"
        node = _make_node(1, "app", node_type="variable")
        result = _make_result("typer_app.py", [node], source=source)
        entries = self.detector.detect({"typer_app.py": result}, [node], {1: node})
        typer_entries = [e for e in entries if e.rule_name == "typer_app"]
        assert len(typer_entries) == 1

    def test_celery_entry(self):
        """Celery() detected."""
        source = "from celery import Celery\napp = Celery()\n"
        node = _make_node(1, "app", node_type="variable")
        result = _make_result("celery_app.py", [node], source=source)
        entries = self.detector.detect({"celery_app.py": result}, [node], {1: node})
        celery_entries = [e for e in entries if e.rule_name == "celery_app"]
        assert len(celery_entries) == 1

    def test_celery_entry_qualified(self):
        """celery.Celery() detected."""
        source = "import celery\napp = celery.Celery()\n"
        node = _make_node(1, "app", node_type="variable")
        result = _make_result("celery_app.py", [node], source=source)
        entries = self.detector.detect({"celery_app.py": result}, [node], {1: node})
        celery_entries = [e for e in entries if e.rule_name == "celery_app"]
        assert len(celery_entries) == 1

    def test_pytest_plugin_entry(self):
        """conftest.py with pytest_addoption detected."""
        source = "def pytest_addoption(parser):\n    pass\n"
        node = _make_node(1, "pytest_addoption", node_type="function")
        result = _make_result("conftest.py", [node], source=source)
        entries = self.detector.detect({"conftest.py": result}, [node], {1: node})
        plugin_entries = [e for e in entries if e.rule_name == "pytest_plugin"]
        assert len(plugin_entries) == 1

    def test_pytest_plugin_fixture(self):
        """conftest.py with @pytest.fixture detected."""
        source = (
            "import pytest\n"
            "@pytest.fixture\n"
            "def my_fixture():\n"
            "    pass\n"
        )
        node = _make_node(1, "my_fixture", node_type="function")
        result = _make_result("conftest.py", [node], source=source)
        entries = self.detector.detect({"conftest.py": result}, [node], {1: node})
        plugin_entries = [e for e in entries if e.rule_name == "pytest_plugin"]
        assert len(plugin_entries) == 1

    def test_custom_rule_function_call(self):
        """Custom rule with function_call: pattern."""
        custom_rules = DEFAULT_RULES + [
            {
                "name": "custom_entry",
                "file_pattern": "**/*.py",
                "ast_pattern": "function_call:custom_func",
                "enabled": True,
            },
        ]
        detector = EntryPointDetector(custom_rules)
        source = "custom_func()\n"
        node = _make_node(1, "custom_func", node_type="function")
        result = _make_result("custom.py", [node], source=source)
        entries = detector.detect({"custom.py": result}, [node], {1: node})
        custom_entries = [e for e in entries if e.rule_name == "custom_entry"]
        assert len(custom_entries) == 1

    def test_custom_rule_function_def(self):
        """Custom rule with function_def: pattern."""
        custom_rules = DEFAULT_RULES + [
            {
                "name": "custom_entry",
                "file_pattern": "**/*.py",
                "ast_pattern": "function_def:my_handler",
                "enabled": True,
            },
        ]
        detector = EntryPointDetector(custom_rules)
        source = "def my_handler():\n    pass\n"
        node = _make_node(1, "my_handler", node_type="function")
        result = _make_result("custom.py", [node], source=source)
        entries = detector.detect({"custom.py": result}, [node], {1: node})
        custom_entries = [e for e in entries if e.rule_name == "custom_entry"]
        assert len(custom_entries) == 1

    def test_custom_rule_decorator(self):
        """Custom rule with decorator: pattern."""
        custom_rules = DEFAULT_RULES + [
            {
                "name": "custom_entry",
                "file_pattern": "**/*.py",
                "ast_pattern": "decorator:myapp.route",
                "enabled": True,
            },
        ]
        detector = EntryPointDetector(custom_rules)
        source = (
            "@myapp.route('/')\n"
            "def index():\n"
            "    pass\n"
        )
        node = _make_node(1, "index", node_type="function")
        result = _make_result("custom.py", [node], source=source)
        entries = detector.detect({"custom.py": result}, [node], {1: node})
        custom_entries = [e for e in entries if e.rule_name == "custom_entry"]
        assert len(custom_entries) == 1

    def test_custom_rule_no_pattern_prefix(self):
        """Custom rule without pattern prefix shouldn't crash."""
        custom_rules = DEFAULT_RULES + [
            {
                "name": "custom_entry",
                "file_pattern": "**/custom.py",
                "ast_pattern": "custom_func",
                "enabled": True,
            },
        ]
        detector = EntryPointDetector(custom_rules)
        node = _make_node(1, "custom_func", node_type="function")
        result = _make_result("custom.py", [node], source="custom_func()\n")
        entries = detector.detect({"custom.py": result}, [node], {1: node})
        assert isinstance(entries, list)

    def test_disabled_rule(self):
        """Disabled rule should not produce entries."""
        rules = [
            {
                "name": "fastapi_app",
                "file_pattern": "**/*.py",
                "ast_pattern": "class_instantiation:FastAPI",
                "enabled": False,
            },
        ]
        detector = EntryPointDetector(rules)
        source = "from fastapi import FastAPI\napp = FastAPI()\n"
        node = _make_node(1, "app", node_type="variable")
        result = _make_result("app.py", [node], source=source)
        entries = detector.detect({"app.py": result}, [node], {1: node})
        assert len(entries) == 0

    def test_update_output(self):
        """update_output marks matching nodes as entry points."""
        from graphlint.analyzer._types import EntryInfo
        node = _make_node(1, "main", node_type="function")
        entries = [EntryInfo(
            rule_name="test",
            file_path="test.py",
            line=1,
            node_id=1,
        )]
        node_id_by_key = {1: node}
        EntryPointDetector.update_output(entries, node_id_by_key)
        assert node.is_entry is True
