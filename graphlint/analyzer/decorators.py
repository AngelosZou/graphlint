# -*- coding: utf-8 -*-
"""Decorator relationship resolution."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class DecoratorInfo:
    """Decorator information."""

    name: str = ""
    qualified_name: str = ""
    args: list[str] = field(default_factory=list)
    is_builtin: bool = False


# Built-in decorator names
_BUILTIN_DECORATORS: frozenset[str] = frozenset(
    {
        "staticmethod",
        "classmethod",
        "property",
        "abstractmethod",
    }
)


class DecoratorResolver:
    """Resolves decorators to qualified names and detects deprecation."""

    def __init__(self, current_module: str = "") -> None:
        """Initialize the resolver."""
        self.current_module: str = current_module

    # ------------------------------------------------------------------
    # Main resolution
    # ------------------------------------------------------------------

    def resolve(self, decorator: ast.expr, current_module: str = "") -> DecoratorInfo:
        """Resolve a single decorator AST node to qualified name."""
        mod = current_module or self.current_module

        # Strip outer Call wrapper
        actual_decorator = decorator
        call_args: list[str] = []
        if isinstance(decorator, ast.Call):
            actual_decorator = decorator.func
            call_args = [self._expr_to_repr(a) for a in decorator.args]

        # Resolve name
        if isinstance(actual_decorator, ast.Name):
            short_name = actual_decorator.id
            qualified = f"{mod}.{short_name}" if mod else short_name
            return DecoratorInfo(
                name=short_name,
                qualified_name=qualified,
                args=call_args,
                is_builtin=short_name in _BUILTIN_DECORATORS,
            )

        elif isinstance(actual_decorator, ast.Attribute):
            # @mod.dec or @mod.sub.dec
            short_name = actual_decorator.attr
            qualified = self._resolve_attribute_chain(actual_decorator)
            return DecoratorInfo(
                name=short_name,
                qualified_name=qualified,
                args=call_args,
                is_builtin=short_name in _BUILTIN_DECORATORS,
            )

        # Fallback for other complex expressions
        return DecoratorInfo(
            name="<unknown>",
            qualified_name="<unknown>",
            args=call_args,
            is_builtin=False,
        )

    def extract_decorator_names(
        self, decorators: List[ast.expr], current_module: str = ""
    ) -> List[DecoratorInfo]:
        """Batch resolve a list of decorators."""
        return [self.resolve(d, current_module) for d in decorators]

    # ------------------------------------------------------------------
    # Deprecation detection
    # ------------------------------------------------------------------

    @staticmethod
    def check_deprecated(
        decorators: List[ast.expr], docstring: str = ""
    ) -> Tuple[bool, str]:
        """Check if a node is marked as deprecated."""
        deprecation_msg = ""

        # Check decorators
        for dec in decorators:
            short_name = ""
            if isinstance(dec, ast.Name):
                short_name = dec.id
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    short_name = dec.func.id
                elif isinstance(dec.func, ast.Attribute):
                    short_name = dec.func.attr
            elif isinstance(dec, ast.Attribute):
                short_name = dec.attr

            if "deprecated" in short_name.lower():
                # Extract message from @deprecated('...') args
                msg_from_args = ""
                if isinstance(dec, ast.Call) and dec.args:
                    first_arg = dec.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(
                        first_arg.value, str
                    ):
                        msg_from_args = first_arg.value
                deprecation_msg = msg_from_args or f"@{short_name} deprecation marker"
                return True, deprecation_msg

        # Check @deprecated tag in docstring
        if docstring and "@deprecated" in docstring:
            for line in docstring.split("\n"):
                stripped = line.strip()
                if stripped.startswith("@deprecated"):
                    deprecation_msg = stripped
                    break
            if not deprecation_msg:
                deprecation_msg = "@deprecated tag in docstring"
            return True, deprecation_msg

        return False, ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_attribute_chain(node: ast.Attribute) -> str:
        """Resolve ast.Attribute chain to qualified name string."""
        parts: List[str] = [node.attr]
        current: ast.expr = node.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        parts.reverse()
        return ".".join(parts)

    @staticmethod
    def _expr_to_repr(node: ast.expr) -> str:
        """Convert AST expression to readable string representation."""
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return DecoratorResolver._resolve_attribute_chain(node)
        if isinstance(node, ast.Call):
            func_repr = DecoratorResolver._expr_to_repr(node.func)
            args_repr = ", ".join(DecoratorResolver._expr_to_repr(a) for a in node.args)
            return f"{func_repr}({args_repr})"
        return "<expr>"
