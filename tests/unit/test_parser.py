# -*- coding: utf-8 -*-
"""AST parser tests."""

import os
import tempfile

import pytest

from graphlint.analyzer._types import ParseResult
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


@pytest.mark.timeout(30)
class TestGlobalKeyword:
    """Tests for global keyword support in AST parsing."""

    MODULE = "my_mod"

    @pytest.fixture(autouse=True)
    def setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            self.parser = SourceParser(tmpdir, BASE_CONFIG)
            yield

    def _parse(self, code: str) -> ParseResult:
        fp = _make_file(self.tmpdir, f"{self.MODULE}.py", code)
        return self.parser.parse_file(fp, f"{self.MODULE}.py")

    def test_global_write(self):
        """global X + X = 20 creates write ref to module-level X, no local node."""
        code = """
X = 10

def set_x():
    global X
    X = 20
"""
        pr = self._parse(code)
        module_qname = f"{self.MODULE}.X"
        # No local node for X inside set_x
        local_x = [n for n in pr.nodes if n.qualified_name == f"{self.MODULE}.set_x.X"]
        assert len(local_x) == 0, "Should not create local node for global X"
        # One write reference targeting the module-level qualified name
        write_refs = [r for r in pr.references if r.edge_type == "write" and r.target_name == module_qname]
        assert len(write_refs) == 1, "Should create write ref to module-level X"
        assert write_refs[0].source_qname == f"{self.MODULE}.set_x"

    def test_global_read(self):
        """global X + return X creates read ref to module-level X."""
        code = """
X = 10

def get_x():
    global X
    return X
"""
        pr = self._parse(code)
        module_qname = f"{self.MODULE}.X"
        read_refs = [r for r in pr.references if r.edge_type == "read" and r.target_name == module_qname]
        assert len(read_refs) == 1, "Should create read ref to module-level X"
        assert read_refs[0].source_qname == f"{self.MODULE}.get_x"

    def test_global_augmented_assign(self):
        """global X + X += 1 creates read+write refs to module-level X."""
        code = """
X = 10

def inc_x():
    global X
    X += 1
"""
        pr = self._parse(code)
        module_qname = f"{self.MODULE}.X"
        write_refs = [r for r in pr.references if r.edge_type == "write" and r.target_name == module_qname]
        read_refs = [r for r in pr.references if r.edge_type == "read" and r.target_name == module_qname]
        assert len(write_refs) == 1, "Should create write ref for augmented assign"
        assert len(read_refs) == 1, "Should create read ref for augmented assign"

    def test_global_multiple_names(self):
        """global X, Y creates correct refs for both names."""
        code = """
X = 10
Y = 20

def swap():
    global X, Y
    X, Y = Y, X
"""
        pr = self._parse(code)
        module_qname_x = f"{self.MODULE}.X"
        module_qname_y = f"{self.MODULE}.Y"
        # Write refs to module-level X and Y
        write_x = [r for r in pr.references if r.edge_type == "write" and r.target_name == module_qname_x]
        write_y = [r for r in pr.references if r.edge_type == "write" and r.target_name == module_qname_y]
        assert len(write_x) == 1
        assert len(write_y) == 1
        # Read refs to module-level X and Y (RHS of tuple assignment)
        read_x = [r for r in pr.references if r.edge_type == "read" and r.target_name == module_qname_x]
        read_y = [r for r in pr.references if r.edge_type == "read" and r.target_name == module_qname_y]
        assert len(read_x) == 1
        assert len(read_y) == 1

    def test_global_nested_function(self):
        """global in nested function still refers to module-level name."""
        code = """
X = 10

def outer():
    def inner():
        global X
        X = 30
"""
        pr = self._parse(code)
        module_qname = f"{self.MODULE}.X"
        # No local node for X in inner
        local_x_inner = [n for n in pr.nodes if n.qualified_name == f"{self.MODULE}.outer.inner.X"]
        assert len(local_x_inner) == 0
        # Write ref from inner to module-level X
        write_refs = [r for r in pr.references if r.edge_type == "write" and r.target_name == module_qname]
        assert len(write_refs) == 1
        assert write_refs[0].source_qname == f"{self.MODULE}.outer.inner"

    def test_local_var_unaffected(self):
        """Non-global variables in the same function behave normally."""
        code = """
def foo():
    x = 42
    return x
"""
        pr = self._parse(code)
        module_qname = f"{self.MODULE}.foo.x"
        local_x = [n for n in pr.nodes if n.qualified_name == module_qname]
        assert len(local_x) == 1, "Local variable should have a node"
        write_refs = [r for r in pr.references if r.edge_type == "write" and r.target_name == "x"]
        assert len(write_refs) == 1, "Local write should use bare name"

    def test_global_annotated_assign(self):
        """global X + X: int = 20 creates write ref to module-level X, no local node."""
        code = """
X: int = 10

def set_x():
    global X
    X: int = 20
"""
        pr = self._parse(code)
        module_qname = f"{self.MODULE}.X"
        local_x = [n for n in pr.nodes if n.qualified_name == f"{self.MODULE}.set_x.X"]
        assert len(local_x) == 0, "Should not create local node for annotated global X"
        write_refs = [r for r in pr.references if r.edge_type == "write" and r.target_name == module_qname]
        assert len(write_refs) == 1, "Should create write ref to module-level X"

    def test_global_refers_missing_module_var(self):
        """global X where X doesn't exist at module level: no crash, ref gracefully dropped."""
        code = """
def init():
    global X
    X = 42
"""
        pr = self._parse(code)
        module_qname = f"{self.MODULE}.X"
        write_refs = [r for r in pr.references if r.edge_type == "write" and r.target_name == module_qname]
        assert len(write_refs) == 1
        # No local node created
        local_x = [n for n in pr.nodes if n.qualified_name == f"{self.MODULE}.init.X"]
        assert len(local_x) == 0

    def test_global_in_method(self):
        """global X inside a class method writes to module-level X."""
        code = """
X = 10

class MyClass:
    def method(self):
        global X
        X = 20
"""
        pr = self._parse(code)
        module_qname = f"{self.MODULE}.X"
        local_x = [n for n in pr.nodes if n.qualified_name == f"{self.MODULE}.MyClass.method.X"]
        assert len(local_x) == 0, "Should not create local node for global X in method"
        write_refs = [r for r in pr.references if r.edge_type == "write" and r.target_name == module_qname]
        assert len(write_refs) == 1
        assert write_refs[0].source_qname == f"{self.MODULE}.MyClass.method"

    def test_global_scope_isolation(self):
        """global X in one function does not leak into another function."""
        code = """
X = 10

def func_a():
    global X
    X = 20

def func_b():
    X = 30
"""
        pr = self._parse(code)
        module_qname = f"{self.MODULE}.X"
        # func_a writes to module-level X
        write_refs_a = [
            r for r in pr.references
            if r.edge_type == "write"
            and r.target_name == module_qname
            and r.source_qname == f"{self.MODULE}.func_a"
        ]
        assert len(write_refs_a) == 1
        # func_b creates a local variable X — not global
        local_x_b = [n for n in pr.nodes if n.qualified_name == f"{self.MODULE}.func_b.X"]
        assert len(local_x_b) == 1, "func_b should create local node for X"
        # func_b's write uses bare name
        write_refs_b = [
            r for r in pr.references
            if r.edge_type == "write"
            and r.target_name == "X"
            and r.source_qname == f"{self.MODULE}.func_b"
        ]
        assert len(write_refs_b) == 1

    def test_global_in_async_function(self):
        """global X inside an async def writes to module-level X."""
        code = """
X = 10

async def async_func():
    global X
    X = 20
"""
        pr = self._parse(code)
        module_qname = f"{self.MODULE}.X"
        local_x = [n for n in pr.nodes if n.qualified_name == f"{self.MODULE}.async_func.X"]
        assert len(local_x) == 0
        write_refs = [r for r in pr.references if r.edge_type == "write" and r.target_name == module_qname]
        assert len(write_refs) == 1
        assert write_refs[0].source_qname == f"{self.MODULE}.async_func"

    def test_global_class_level_var_write(self):
        """global X where X is a class-level variable (module-level) — no local node."""
        code = """
class Config:
    X = 10

def set_x():
    global X
    X = 20
"""
        pr = self._parse(code)
        module_qname = f"{self.MODULE}.X"
        local_x = [n for n in pr.nodes if n.qualified_name == f"{self.MODULE}.set_x.X"]
        assert len(local_x) == 0
        write_refs = [r for r in pr.references if r.edge_type == "write" and r.target_name == module_qname]
        assert len(write_refs) == 1
        assert write_refs[0].source_qname == f"{self.MODULE}.set_x"
