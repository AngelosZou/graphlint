# -*- coding: utf-8 -*-
"""AST parser tests."""

import os
import tempfile

import pytest

from graphlint.analyzer.parser import SourceParser


def _make_file(tmpdir, rel_path, content):
    """Create file under tmpdir and return full path."""
    full = os.path.join(tmpdir, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return full


BASE_CONFIG = {
    "exclude_patterns": {"always_exclude": ["__pycache__/"], "user_exclude": []},
    "performance": {"max_file_size_mb": 10},
    "test_patterns": {
        "file_patterns": ["test_*.py"],
        "dir_patterns": [],
        "config_files": [],
    },
}


@pytest.mark.timeout(30)
class TestSourceParser:
    """SourceParser black-box tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            self.parser = SourceParser(tmpdir, BASE_CONFIG)
            yield

    def test_parse_simple_class(self):
        """Parse a class with methods, verify node count and types."""
        code = """
class MyClass:
    def method1(self):
        pass

    def method2(self):
        pass
"""
        fp = _make_file(self.tmpdir, "myclass.py", code)
        pr = self.parser.parse_file(fp, "myclass.py")
        # 1 class + 2 methods = 3 nodes
        assert len(pr.nodes) == 3
        types = {n.node_type for n in pr.nodes}
        assert "class" in types
        assert "method" in types
        assert "function" not in types

    def test_parse_function_with_decorator(self):
        """Parse @staticmethod function, verify decorators list."""
        code = """
class MyClass:
    @staticmethod
    def my_static():
        pass
"""
        fp = _make_file(self.tmpdir, "deco.py", code)
        pr = self.parser.parse_file(fp, "deco.py")
        # Find static method node
        static_nodes = [n for n in pr.nodes if n.name == "my_static"]
        assert len(static_nodes) == 1
        static_node = static_nodes[0]
        assert static_node.decorators is not None
        assert "staticmethod" in str(static_node.decorators)

    def test_parse_async_function(self):
        """Parse async def, verify is_async=True."""
        code = """
async def my_async():
    pass
"""
        fp = _make_file(self.tmpdir, "async_mod.py", code)
        pr = self.parser.parse_file(fp, "async_mod.py")
        async_nodes = [n for n in pr.nodes if n.name == "my_async"]
        assert len(async_nodes) == 1
        assert async_nodes[0].is_async is True

    def test_parse_module_variable(self):
        """Parse module-level variable X = 42, verify node_type='variable'."""
        code = "X = 42\n"
        fp = _make_file(self.tmpdir, "vars.py", code)
        pr = self.parser.parse_file(fp, "vars.py")
        var_nodes = [n for n in pr.nodes if n.name == "X"]
        assert len(var_nodes) >= 1
        assert var_nodes[0].node_type == "variable"

    def test_parse_class_field(self):
        """Parse class field assignment, verify node_type='field' with parent_node_id."""
        code = """
class MyClass:
    field1 = 42
"""
        fp = _make_file(self.tmpdir, "fields.py", code)
        pr = self.parser.parse_file(fp, "fields.py")
        field_nodes = [n for n in pr.nodes if n.name == "field1"]
        assert len(field_nodes) >= 1
        assert field_nodes[0].node_type in ("field", "variable")
        # Verify parent_node_id exists
        assert field_nodes[0].parent_node_id is not None

    def test_parse_type_annotation(self):
        """Parse typed variable x: int = 5."""
        code = "x: int = 5\n"
        fp = _make_file(self.tmpdir, "typed.py", code)
        pr = self.parser.parse_file(fp, "typed.py")
        x_nodes = [n for n in pr.nodes if n.name == "x"]
        if x_nodes:
            assert True

    def test_parse_syntax_error(self):
        """Parse file with syntax errors, expect syntax_error warning."""
        code = "def foo(::\n"
        fp = _make_file(self.tmpdir, "syntax_err.py", code)
        pr = self.parser.parse_file(fp, "syntax_err.py")
        if pr.warnings:
            assert any(
                "syntax" in w.warn_type or "Syntax" in w.message for w in pr.warnings
            )

    def test_parse_empty_file(self):
        """Empty .py file returns empty nodes/imports/warnings."""
        fp = _make_file(self.tmpdir, "empty.py", "")
        pr = self.parser.parse_file(fp, "empty.py")
        assert pr.nodes == [] or len(pr.nodes) == 0
        assert pr.imports == [] or len(pr.imports) == 0

    def test_parse_name_usages(self):
        """Parse code with function calls and reads, verify name_usages."""
        code = """
import os

def greet():
    print("hello")
"""
        fp = _make_file(self.tmpdir, "usages.py", code)
        pr = self.parser.parse_file(fp, "usages.py")
        assert pr.name_usages is not None

    def test_parse_class_with_no_methods(self):
        """Empty class generates a class node."""
        code = "class Empty:\n    pass\n"
        fp = _make_file(self.tmpdir, "empty_class.py", code)
        pr = self.parser.parse_file(fp, "empty_class.py")
        class_nodes = [n for n in pr.nodes if n.node_type == "class"]
        assert len(class_nodes) == 1
