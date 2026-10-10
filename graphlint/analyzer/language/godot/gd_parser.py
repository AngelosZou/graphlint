# -*- coding: utf-8 -*-
"""GDScript source parser (tree-sitter based)."""

from __future__ import annotations

from typing import Any, Optional

from graphlint.analyzer._types import ParseResult

from . import constants as gd_constants
from .constants import _file_to_module
from .imports import find_unused_resource_imports
from .visitor import GdVisitor


def parse_gd(
    file_path: str,
    source: str,
    config: Optional[dict[str, Any]] = None,
) -> ParseResult:
    """Parse one GDScript file into a :class:`ParseResult`."""
    result = ParseResult(file_path=file_path)
    result.source = source

    if not gd_constants._TREE_SITTER_GDSCRIPT_AVAILABLE:
        result.warnings.append(
            _make_warning(
                "syntax_error",
                "error",
                "tree-sitter-gdscript not installed; install with: "
                "pip install graphlint[godot]",
                file_path,
            )
        )
        return result

    try:
        import tree_sitter

        parser = tree_sitter.Parser()
        language = gd_constants._get_gdscript_language()
        if hasattr(parser, "set_language"):
            parser.set_language(language)
        else:  # pragma: no cover - older py-tree-sitter
            parser.language = language
        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)
    except Exception as exc:
        result.warnings.append(
            _make_warning(
                "syntax_error", "error",
                f"Parse error in {file_path}: {exc}", file_path,
            )
        )
        return result

    module_qname = _file_to_module(file_path)
    try:
        visitor = GdVisitor(module_qname, file_path, source_bytes, config)
        visitor.visit(tree)
    except Exception as exc:
        result.warnings.append(
            _make_warning(
                "syntax_error", "error",
                f"Visit error in {file_path}: {exc}", file_path,
            )
        )
        return result

    result.nodes = visitor.nodes
    result.imports = list(visitor.imports)
    result.name_usages = visitor.name_usages
    result.references = visitor.references
    result.warnings.extend(visitor.warnings)

    # Metadata consumed by the cross-file validation pass
    # (``GodotAdapter.validate_graph``): whether the script contains an
    # unprovable dynamic dispatch (which forbids "provably unused" verdicts),
    # the declared ``class_name`` alias and the qname of the member owner.
    setattr(result, "godot_dynamic", bool(visitor.dynamic))
    setattr(result, "godot_class_name", visitor.class_name)
    setattr(result, "godot_member_qnames", dict(visitor.member_qnames))
    setattr(result, "godot_owner_qname", visitor.owner_qname)
    setattr(result, "godot_dispatch_names", set(visitor.dispatch_names))
    setattr(result, "godot_dynamic_lines", list(visitor.dynamic_lines))

    error_node = _first_error(tree.root_node)
    if error_node is not None:
        line = error_node.start_point[0] + 1
        result.warnings.append(
            _make_warning(
                "syntax_error",
                "error",
                f"Syntax error in {file_path} at line {line}",
                file_path,
                line=line,
            )
        )

    for _imp, message, line in find_unused_resource_imports(
        result.imports, result.name_usages, file_path
    ):
        result.warnings.append(
            _make_warning("unused_import", "warning", message, file_path, line=line)
        )

    # An unprovable dynamic construct (a computed ``load``/``get_node``, a
    # ``call(name)`` whose name is not a literal, ...) means liveness cannot be
    # proven for this file: report it as information, never as a dead-code
    # verdict (plan §6.5.3).  The gate in the visitor has already widened the
    # keep-alive edges, so the advisory explains why a file looks suspiciously
    # alive.
    if visitor.dynamic:
        _lines = sorted(set(getattr(visitor, "dynamic_lines", []) or []))
        _where = f" (line {_lines[0]})" if _lines else ""
        result.warnings.append(
            _make_warning(
                "dynamic_import",
                "info",
                f"Dynamic dispatch or computed resource path in this script{_where}: "
                "member usage cannot be proven statically",
                file_path,
                line=_lines[0] if _lines else 1,
            )
        )

    return result


def _first_error(root: Any) -> Any:
    """Return the first ``ERROR``/``MISSING`` node, breadth-first, or ``None``."""
    stack = [root]
    while stack:
        node = stack.pop(0)
        if node.is_missing:
            return node
        for child in node.children:
            if child.type == "ERROR" or child.has_error:
                if child.type == "ERROR":
                    return child
                stack.append(child)
    return None


def _make_warning(
    warn_type: str,
    severity: str,
    message: str,
    file_path: str,
    line: int = 0,
    node_id: int = 0,
) -> Any:
    from graphlint.analyzer.warnings import WarningInfo

    return WarningInfo(
        warn_type=warn_type,
        severity=severity,
        message=message,
        file_path=file_path,
        line=line,
        node_id=node_id,
    )
