# -*- coding: utf-8 -*-
"""Decorator resolution tests."""

import ast

import pytest

from graphlint.analyzer.decorators import DecoratorInfo, DecoratorResolver


def _parse_expr(code: str) -> ast.expr:
    """Parse expression code to AST node."""
    return ast.parse(code, mode="eval").body


@pytest.mark.timeout(30)
class TestDecoratorResolver:
    """DecoratorResolver black-box tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.resolver = DecoratorResolver(current_module="mymod")

    def test_decorator_edge_creation(self):
        """@dec1 resolves to decorator info."""
        decorator_ast = _parse_expr("dec1")
        info = self.resolver.resolve(decorator_ast, "mymod")
        assert isinstance(info, DecoratorInfo)
        assert info.name == "dec1"
        assert info.qualified_name == "mymod.dec1"

    def test_multi_decorator_chain(self):
        """@dec2 @dec1 chained decorators resolve individually."""
        code = """
@dec2
@dec1
def func():
    pass
"""
        tree = ast.parse(code.strip())
        func_def = tree.body[0]
        assert isinstance(func_def, ast.FunctionDef)
        infos = self.resolver.extract_decorator_names(func_def.decorator_list, "mymod")
        assert len(infos) == 2
        # Decorator order: @dec2 first (first in list)
        assert infos[0].name == "dec2"
        assert infos[1].name == "dec1"

    def test_decorator_with_args(self):
        """@dec1(args) extracts arguments in repr format."""
        decorator_ast = _parse_expr("dec1(42, 'hello')")
        info = self.resolver.resolve(decorator_ast, "mymod")
        assert info.name == "dec1"
        assert info.args is not None
        assert "42" in info.args
        # Args stored as repr(), so 'hello' shows as "'hello'" in list
        assert any("hello" in a for a in info.args)

    def test_module_decorator(self):
        """@utils.decorators.deprecated resolves to qualified name."""
        decorator_ast = _parse_expr("utils.decorators.deprecated")
        info = self.resolver.resolve(decorator_ast, "mymod")
        assert info.qualified_name == "utils.decorators.deprecated"
        assert info.name == "deprecated"

    def test_nested_decorator(self):
        """@outer.inner() resolves to qualified name."""
        decorator_ast = _parse_expr("outer.inner()")
        info = self.resolver.resolve(decorator_ast, "mymod")
        assert info.qualified_name == "outer.inner"
        assert info.args is not None

    def test_deprecated_check(self):
        """@deprecated detected as deprecated."""
        decorator_ast = _parse_expr("deprecated")
        is_dep, msg = self.resolver.check_deprecated([decorator_ast], "")
        assert is_dep is True

    def test_deprecated_with_message(self):
        """@deprecated('Use X instead') extracts deprecation message."""
        decorator_ast = _parse_expr("deprecated('Use X instead')")
        is_dep, msg = self.resolver.check_deprecated([decorator_ast], "")
        assert is_dep is True
        assert "Use X instead" in msg

    def test_deprecated_in_docstring(self):
        """@deprecated in docstring should also be detected."""
        docstring = "This function is deprecated.\n@deprecated Use new_func."
        is_dep, msg = self.resolver.check_deprecated([], docstring)
        assert is_dep is True
        assert "Use new_func" in msg

    def test_no_deprecated(self):
        """No @deprecated decorator returns False."""
        decorator_ast = _parse_expr("some_other_decorator")
        is_dep, msg = self.resolver.check_deprecated([decorator_ast], "")
        assert is_dep is False
        assert msg == ""

    def test_third_party_decorator(self):
        """Decorator not in project — resolve name, no edge."""
        decorator_ast = _parse_expr("some_external_lib.decorator")
        info = self.resolver.resolve(decorator_ast, "mymod")
        assert info.qualified_name == "some_external_lib.decorator"
        assert info.name == "decorator"

    def test_extract_empty_list(self):
        """Empty decorator list returns empty list."""
        infos = self.resolver.extract_decorator_names([], "mymod")
        assert infos == []
