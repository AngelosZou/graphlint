# -*- coding: utf-8 -*-
"""Tests for the C language adapter."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest

from graphlint.analyzer._types import GraphBuildResult, NodeInfo
from graphlint.analyzer.warnings import WarningCollector
from graphlint.analyzer.language.c.constants import (
    _TREE_SITTER_C_AVAILABLE,
    _file_to_module,
    _is_test_file,
)
from graphlint.analyzer.language.c.imports import CImportAnalyzer
from graphlint.analyzer.language.c.visitor import CVisitor


tree_sitter_available = pytest.mark.skipif(
    not _TREE_SITTER_C_AVAILABLE, reason="tree-sitter-c not installed"
)


# =============================================================================
# Constants tests (always runnable)
# =============================================================================


class TestCConstants:
    def test_file_to_module(self):
        assert _file_to_module("src/main.c") == "src.main"
        assert _file_to_module("lib/utils/helper.c") == "lib.utils.helper"
        assert _file_to_module("include/header.h") == "include.header"
        assert _file_to_module("runner.py") == ""

    def test_is_test_file(self):
        config = {}
        assert _is_test_file("tests/test_foo.c", config) is True
        assert _is_test_file("test/test_bar.c", config) is True
        assert _is_test_file("tests/my_test.c", config) is True
        assert _is_test_file("src/main.c", config) is False
        assert _is_test_file("test_main.c", config) is True
        assert _is_test_file("lib/foo_test.c", config) is True

    def test_is_test_file_header(self):
        config = {}
        assert _is_test_file("tests/test_foo.h", config) is True
        assert _is_test_file("src/main.h", config) is False

    def test_is_test_file_exact_test_basename(self):
        config = {}
        assert _is_test_file("src/latest.c", config) is False
        assert _is_test_file("src/contest.c", config) is False
        assert _is_test_file("src/attest.c", config) is False
        assert _is_test_file("src/util.c", config) is False
        assert _is_test_file("src/test.c", config) is True
        assert _is_test_file("src/test.h", config) is True
        assert _is_test_file("src/util_test.c", config) is True
        assert _is_test_file("src/foo_test.h", config) is True


# =============================================================================
# Adapter registration tests (always runnable)
# =============================================================================


class TestCAdapterRegistration:
    def test_adapter_imports_gracefully(self):
        from graphlint.analyzer.language.c import CAdapter
        adapter = CAdapter()
        assert adapter.language_name == "c"
        assert ".c" in adapter.file_extensions
        assert adapter.is_special_name("main") is True
        assert adapter.is_special_name("Main") is True
        assert adapter.is_special_name("RandomFunc") is False

    def test_registry_skips_c_gracefully(self):
        from graphlint.api import _build_registry
        registry = _build_registry()
        adapter = registry.adapter_for_file("test.c")
        if _TREE_SITTER_C_AVAILABLE:
            assert adapter is not None
        else:
            assert adapter is None

    def test_is_special_name_pattern(self):
        from graphlint.analyzer.language.c import CAdapter
        adapter = CAdapter()
        assert adapter.is_special_name("main")
        assert adapter.is_special_name("Main")
        assert adapter.is_special_name("WinMain")
        assert not adapter.is_special_name("calculate")


# =============================================================================
# Visitor tests (require tree-sitter-c)
# =============================================================================


def _parse_source(source: str, module_qname: str = "test_module",
                  file_name: str = "test.c") -> CVisitor:
    import tree_sitter
    from graphlint.analyzer.language.c.constants import _get_c_language

    lang = _get_c_language()
    parser = tree_sitter.Parser()
    if hasattr(parser, "set_language"):
        parser.set_language(lang)
    else:
        parser.language = lang
    tree = parser.parse(bytes(source, "utf-8"))

    import_analyzer = CImportAnalyzer()
    visitor = CVisitor(module_qname, file_name, import_analyzer)
    visitor.visit(tree)
    visitor.finalize()
    return visitor


@tree_sitter_available
class TestCVisitorBasic:
    """Basic CST visitor tests — simple C parsing."""

    def test_simple_function_parsing(self):
        source = """\
int add(int a, int b) {
    return a + b;
}
"""
        visitor = _parse_source(source)
        nodes = visitor.nodes

        func_nodes = [n for n in nodes if n.node_type == "function"]
        assert len(func_nodes) == 1
        assert func_nodes[0].name == "add"
        assert func_nodes[0].qualified_name == "test_module.add"

    def test_function_with_pointer_param(self):
        source = """\
void process(int *data, size_t len) {
    if (data != NULL) {
        data[0] = 0;
    }
}
"""
        visitor = _parse_source(source)
        nodes = visitor.nodes
        func_nodes = [n for n in nodes if n.node_type == "function"]
        assert len(func_nodes) == 1
        assert func_nodes[0].name == "process"

    def test_multiple_functions(self):
        source = """\
int init(void) { return 0; }
void cleanup(void) { }
int run(const char *arg) { return 0; }
"""
        visitor = _parse_source(source)
        func_nodes = [n for n in visitor.nodes if n.node_type == "function"]
        assert len(func_nodes) == 3
        names = {n.name for n in func_nodes}
        assert names == {"init", "cleanup", "run"}

    def test_struct_definition(self):
        source = """\
struct Point {
    int x;
    int y;
};
"""
        visitor = _parse_source(source)
        nodes = visitor.nodes

        struct_nodes = [n for n in nodes if n.node_type == "struct"]
        assert len(struct_nodes) == 1
        assert struct_nodes[0].name == "Point"

        field_nodes = [n for n in nodes if n.node_type == "field"]
        assert len(field_nodes) == 2
        field_names = {n.name for n in field_nodes}
        assert field_names == {"x", "y"}

    def test_typedef_struct(self):
        source = """\
typedef struct {
    int value;
    char *name;
} Item;
"""
        visitor = _parse_source(source)
        type_nodes = [n for n in visitor.nodes if n.node_type == "type"]
        assert len(type_nodes) == 1
        assert type_nodes[0].name == "Item"

    def test_enum_definition(self):
        source = """\
enum Color {
    RED,
    GREEN,
    BLUE
};
"""
        visitor = _parse_source(source)
        enum_nodes = [n for n in visitor.nodes if n.node_type == "enum"]
        assert len(enum_nodes) == 1
        assert enum_nodes[0].name == "Color"

    def test_typedef_enum(self):
        source = """\
typedef enum {
    STATUS_OK,
    STATUS_ERROR
} Status;
"""
        visitor = _parse_source(source)
        type_nodes = [n for n in visitor.nodes if n.node_type == "type"]
        assert len(type_nodes) == 1
        assert type_nodes[0].name == "Status"

    def test_typedef_function_pointer_node(self):
        source = "typedef void (*callback_t)(void);\n"
        visitor = _parse_source(source)
        names = {n.name for n in visitor.nodes}
        assert "callback_t" in names

    def test_function_pointer_variable_node(self):
        source = "int (*fp)(void);\n"
        visitor = _parse_source(source)
        names = {n.name for n in visitor.nodes}
        assert "fp" in names

    def test_union_definition(self):
        source = """\
union Data {
    int i;
    float f;
    char str[20];
};
"""
        visitor = _parse_source(source)
        union_nodes = [n for n in visitor.nodes if n.node_type == "union"]
        assert len(union_nodes) == 1
        assert union_nodes[0].name == "Data"

    def test_enum_constants_create_member_nodes(self):
        source = """\
enum Color {
    RED,
    GREEN,
    BLUE
};
"""
        visitor = _parse_source(source)
        enum_nodes = [n for n in visitor.nodes if n.node_type == "enum"]
        member_nodes = [n for n in visitor.nodes if n.node_type == "enum_member"]
        assert len(enum_nodes) == 1
        assert len(member_nodes) == 3
        assert {n.name for n in member_nodes} == {"RED", "GREEN", "BLUE"}
        assert {n.qualified_name for n in member_nodes} == {
            "test_module.Color.RED",
            "test_module.Color.GREEN",
            "test_module.Color.BLUE",
        }
        assert all(n.parent_node_id == enum_nodes[0].id for n in member_nodes)
        # The def site must not emit phantom reads from the enum to its own
        # constants.
        phantom = [
            r for r in visitor.references
            if r.source_qname == "test_module.Color"
            and r.target_name in ("RED", "GREEN", "BLUE")
        ]
        assert phantom == []

    def test_enum_constant_use_resolves_to_member(self):
        source = """\
enum Color { RED, GREEN };
int main(void) { return RED; }
"""
        visitor = _parse_source(source)
        uses = [
            r for r in visitor.references
            if r.edge_type == "read" and r.target_name == "RED"
        ]
        assert len(uses) == 1
        assert uses[0].source_qname == "test_module.main"

    def test_typedef_enum_members_under_typedef(self):
        source = """\
typedef enum {
    STATUS_OK,
    STATUS_ERROR
} Status;
"""
        visitor = _parse_source(source)
        type_nodes = [n for n in visitor.nodes if n.node_type == "type"]
        member_nodes = [n for n in visitor.nodes if n.node_type == "enum_member"]
        assert len(type_nodes) == 1
        assert len(member_nodes) == 2
        assert {n.qualified_name for n in member_nodes} == {
            "test_module.Status.STATUS_OK",
            "test_module.Status.STATUS_ERROR",
        }
        assert all(n.parent_node_id == type_nodes[0].id for n in member_nodes)

    def test_mixed_declarator_list_keeps_variable(self):
        source = "int foo(void), bar;\n"
        visitor = _parse_source(source)
        names = {n.name for n in visitor.nodes}
        assert "bar" in names
        assert "foo" not in names
        var_nodes = [n for n in visitor.nodes if n.node_type == "variable"]
        assert len(var_nodes) == 1
        assert var_nodes[0].qualified_name == "test_module.bar"

    def test_multi_name_declaration_two_nodes(self):
        source = "int a, b;\n"
        visitor = _parse_source(source)
        var_nodes = [n for n in visitor.nodes if n.node_type == "variable"]
        assert {n.name for n in var_nodes} == {"a", "b"}

    def test_mixed_pointer_declaration_two_nodes(self):
        source = "char *p, q;\n"
        visitor = _parse_source(source)
        var_nodes = [n for n in visitor.nodes if n.node_type == "variable"]
        assert {n.name for n in var_nodes} == {"p", "q"}

    def test_typedef_field_type_use_emits_read(self):
        source = """\
typedef struct { int x; } Item;
struct Holder { Item item; };
"""
        visitor = _parse_source(source)
        refs = [
            r for r in visitor.references
            if r.target_name == "Item" and r.edge_type == "read"
        ]
        assert refs, "typedef used as a field type must emit a read edge"
        assert all(r.source_qname == "test_module.Holder" for r in refs)

    def test_global_variable(self):
        source = """\
int global_counter = 0;
const char *app_name = "myapp";
"""
        visitor = _parse_source(source)
        var_nodes = [n for n in visitor.nodes if n.node_type == "variable"]
        assert len(var_nodes) == 2
        assert var_nodes[0].name == "global_counter"
        assert var_nodes[1].name == "app_name"
        assert var_nodes[0].qualified_name == "test_module.global_counter"

    def test_macro_definition(self):
        source = """\
#define MAX_SIZE 256
#define SQUARE(x) ((x) * (x))
"""
        visitor = _parse_source(source)
        macro_nodes = [n for n in visitor.nodes if n.node_type == "macro"]
        assert len(macro_nodes) == 2
        assert macro_nodes[0].name == "MAX_SIZE"
        assert macro_nodes[1].name == "SQUARE"


@tree_sitter_available
class TestCVisitorImports:
    """Test that #include directives are captured."""

    def test_local_include_detected(self):
        source = '''\
#include "utils.h"
#include "math/vec.h"
#include <stdio.h>
#include <stdlib.h>
'''
        visitor = _parse_source(source)
        imports = visitor.imports
        assert len(imports) >= 2
        import_paths = {i.include_path for i in imports}
        assert "utils.h" in import_paths
        assert "math/vec.h" in import_paths

    def test_system_includes_skipped(self):
        source = """\
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
"""
        visitor = _parse_source(source)
        imports = visitor.imports
        for imp in imports:
            assert not imp.include_path.startswith("<"), imp.include_path


@tree_sitter_available
class TestCVisitorReferences:
    """Test reference edges emitted by the visitor."""

    def test_call_edge(self):
        source = """\
void helper(void) { }

int main(void) {
    helper();
    return 0;
}
"""
        visitor = _parse_source(source)
        refs = visitor.references

        call_edges = [r for r in refs if r.edge_type == "call"]
        assert len(call_edges) >= 1
        assert any(r.target_name == "helper" for r in call_edges)

    def test_function_pointer_call(self):
        source = """\
typedef void (*callback_t)(void);

void invoke(callback_t cb) {
    cb();
}
"""
        visitor = _parse_source(source)
        refs = visitor.references
        call_edges = [r for r in refs if r.edge_type == "call"]
        assert len(call_edges) >= 1

    def test_variable_read_write(self):
        source = """\
int counter = 0;

void increment(void) {
    counter = counter + 1;
}
"""
        visitor = _parse_source(source)
        refs = visitor.references

        writes = [r for r in refs if r.edge_type == "write" and r.target_name == "counter"]
        reads = [r for r in refs if r.edge_type == "read" and r.target_name == "counter"]
        assert len(writes) >= 1
        assert len(reads) >= 1

    def test_struct_field_access(self):
        source = """\
struct Point {
    int x;
    int y;
};

void move(struct Point *p) {
    p->x = 10;
    p->y = 20;
}
"""
        visitor = _parse_source(source)
        refs = visitor.references
        field_writes = [r for r in refs if r.edge_type == "write" and r.target_name in ("x", "y")]
        assert len(field_writes) >= 2

    def test_struct_member_access_dot(self):
        source = """\
struct Vec { float x, y; };

void print(struct Vec v) {
    float a = v.x;
    float b = v.y;
}
"""
        visitor = _parse_source(source)
        refs = visitor.references
        field_reads = [r for r in refs if r.edge_type == "read" and r.target_name in ("x", "y")]
        assert len(field_reads) >= 2


@tree_sitter_available
class TestCVisitorEdgeCases:
    """Edge cases for the C visitor."""

    def test_empty_file(self):
        source = ""
        visitor = _parse_source(source)
        assert len(visitor.nodes) == 0
        assert len(visitor.warnings) == 0

    def test_comments_ignored(self):
        source = """\
/* This is a comment
   with multiple lines */
// single line comment
int foo(void) { return 42; }
"""
        visitor = _parse_source(source)
        func_nodes = [n for n in visitor.nodes if n.node_type == "function"]
        assert len(func_nodes) == 1
        assert func_nodes[0].name == "foo"

    def test_include_guard_header_walks_body(self):
        source = """\
#ifndef GUARD_H
#define GUARD_H
int helper(void) { return 42; }
#endif
"""
        visitor = _parse_source(source, file_name="guard.h")
        func_nodes = [n for n in visitor.nodes if n.node_type == "function"]
        assert len(func_nodes) == 1
        assert func_nodes[0].name == "helper"

    def test_include_guard_c_walks_body(self):
        source = """\
#ifndef GUARD_H
#define GUARD_H
int helper(void) { return 42; }
#endif
"""
        visitor = _parse_source(source, file_name="guard.c")
        func_nodes = [n for n in visitor.nodes if n.node_type == "function"]
        assert len(func_nodes) == 1
        assert func_nodes[0].name == "helper"

    def test_conditional_compilation_walks_all_branches(self):
        source = """\
#ifdef FEATURE
int feature_fn(void) { return 1; }
#else
int fallback_fn(void) { return 0; }
#endif
"""
        visitor = _parse_source(source)
        func_nodes = [n for n in visitor.nodes if n.node_type == "function"]
        names = {n.name for n in func_nodes}
        assert names == {"feature_fn", "fallback_fn"}

    def test_nested_struct(self):
        source = """\
struct Outer {
    struct Inner {
        int value;
    } inner;
    int count;
};
"""
        visitor = _parse_source(source)
        struct_nodes = [n for n in visitor.nodes if n.node_type == "struct"]
        assert len(struct_nodes) == 2
        names = {n.name for n in struct_nodes}
        assert names == {"Outer", "Inner"}

    def test_function_prototype_ignored(self):
        source = """\
int future_func(int a, int b);

int main(void) {
    return 0;
}
"""
        visitor = _parse_source(source)
        func_nodes = [n for n in visitor.nodes if n.node_type == "function"]
        names = {n.name for n in func_nodes}
        assert "future_func" not in names
        assert "main" in names

    def test_static_function(self):
        source = """\
static int private_util(int x) {
    return x * 2;
}

int public_api(void) {
    return private_util(5);
}
"""
        visitor = _parse_source(source)
        func_nodes = [n for n in visitor.nodes if n.node_type == "function"]
        assert len(func_nodes) == 2
        names = {n.name for n in func_nodes}
        assert names == {"private_util", "public_api"}

    def test_extern_variable(self):
        source = """\
extern int external_var;
int internal_var;
"""
        visitor = _parse_source(source)
        var_nodes = [n for n in visitor.nodes if n.node_type == "variable"]
        names = {n.name for n in var_nodes}
        assert "external_var" in names
        assert "internal_var" in names

    def test_forward_declaration_no_node(self):
        source = "int foo(void);\n"
        visitor = _parse_source(source)
        names = {n.name for n in visitor.nodes}
        assert "foo" not in names

    def test_forward_declaration_pointer_return_no_node(self):
        source = "int *foo(void);\n"
        visitor = _parse_source(source)
        names = {n.name for n in visitor.nodes}
        assert "foo" not in names

    def test_forward_declaration_initializer_no_node(self):
        source = "int foo(void) = 0;\n"
        visitor = _parse_source(source)
        names = {n.name for n in visitor.nodes}
        assert "foo" not in names

    def test_pointer_field_no_self_read(self):
        source = """\
struct S {
    char *name;
    int count;
};
"""
        visitor = _parse_source(source)
        field_nodes = [n for n in visitor.nodes if n.node_type == "field"]
        field_names = {n.name for n in field_nodes}
        assert field_names == {"name", "count"}
        self_refs = [
            r for r in visitor.references
            if r.target_name in ("name", "count")
            and r.source_qname == "test_module.S"
        ]
        assert self_refs == []

    # --- #2 nested-declarator fields ---------------------------------------

    def test_nested_pointer_field_node(self):
        source = """\
struct S {
    char *name;
    int count;
    char **pp;
};
"""
        visitor = _parse_source(source)
        field_nodes = [n for n in visitor.nodes if n.node_type == "field"]
        field_names = {n.name for n in field_nodes}
        assert "pp" in field_names
        self_refs = [
            r for r in visitor.references
            if r.target_name == "pp" and r.source_qname == "test_module.S"
        ]
        assert self_refs == []

    def test_function_pointer_field_node(self):
        source = """\
struct S {
    void (*cb)(int);
};
"""
        visitor = _parse_source(source)
        field_nodes = [n for n in visitor.nodes if n.node_type == "field"]
        field_names = {n.name for n in field_nodes}
        assert "cb" in field_names
        self_refs = [
            r for r in visitor.references
            if r.target_name == "cb" and r.source_qname == "test_module.S"
        ]
        assert self_refs == []

    def test_nested_array_field_node(self):
        source = """\
struct M {
    int m[4][5];
    int n[3];
};
"""
        visitor = _parse_source(source)
        field_nodes = [n for n in visitor.nodes if n.node_type == "field"]
        field_names = {n.name for n in field_nodes}
        assert "m" in field_names
        assert "n" in field_names
        self_refs = [
            r for r in visitor.references
            if r.target_name in ("m", "n") and r.source_qname == "test_module.M"
        ]
        assert self_refs == []

    # --- #1 anonymous struct/union/enum definitions ------------------------

    def test_typedef_anonymous_struct_no_phantom_node(self):
        source = """\
typedef struct {
    int x;
} Item;
"""
        visitor = _parse_source(source)
        item_nodes = [
            n for n in visitor.nodes if n.qualified_name == "test_module.Item"
        ]
        assert len(item_nodes) == 1
        assert item_nodes[0].node_type == "type"
        assert item_nodes[0].name == "Item"
        # No phantom anonymous node with an empty name.
        assert all(n.name != "" for n in visitor.nodes)

    def test_anonymous_struct_in_function_not_clobbered(self):
        source = """\
void f(void) {
    struct { int a; } s;
}
"""
        visitor = _parse_source(source)
        func_nodes = [n for n in visitor.nodes if n.node_type == "function"]
        assert len(func_nodes) == 1
        assert func_nodes[0].name == "f"
        assert func_nodes[0].qualified_name == "test_module.f"
        # No phantom anonymous struct node.
        assert all(n.name != "" for n in visitor.nodes)
        field_nodes = [n for n in visitor.nodes if n.node_type == "field"]
        assert len(field_nodes) == 1
        assert field_nodes[0].name == "a"
        assert field_nodes[0].qualified_name == "test_module.f.a"



# =============================================================================
# Entry detection tests (require tree-sitter-c)
# =============================================================================


@tree_sitter_available
class TestCEntryDetection:
    """Entry detection for C programs."""

    def _detect_entries(self, source: str, rules: list[dict] | None = None,
                        file_name: str = "src/main.c") -> list[Any]:
        import tempfile
        from graphlint.analyzer.language.c.entry import CEntryPointDetector
        from graphlint.analyzer.language.c.parser import CSourceParser

        if rules is None:
            rules = [{
                "name": "c_main",
                "file_pattern": "**/*.c",
                "ast_pattern": "function_def:main",
                "enabled": True,
            }]
        tmp = tempfile.mkdtemp()
        full = os.path.join(tmp, file_name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(source)
        config = {"_root_dir": tmp, "entry_rules": rules}
        pr = CSourceParser(tmp, config).parse_file(full)
        rel = os.path.relpath(full, tmp).replace(os.sep, "/")
        detector = CEntryPointDetector(config)
        return detector.detect({rel: pr}, pr.nodes, {})

    def test_main_function_detected(self):
        source = """\
int main(void) {
    return 0;
}
"""
        entries = self._detect_entries(source)
        assert len(entries) >= 1
        assert any(e.rule_name == "c_main" for e in entries)

    def test_main_with_args_detected(self):
        source = """\
int main(int argc, char *argv[]) {
    return 0;
}
"""
        entries = self._detect_entries(source)
        main_entries = [e for e in entries if e.rule_name == "c_main"]
        assert len(main_entries) >= 1

    def test_custom_entry_pattern(self):
        source = """\
int my_entry_point(void) {
    return 0;
}
"""
        rules = [{
            "name": "custom_c_entry",
            "file_pattern": "**/*.c",
            "ast_pattern": "function_def:my_entry_point",
            "enabled": True,
        }]
        entries = self._detect_entries(source, rules)
        assert len(entries) >= 1
        assert entries[0].rule_name == "custom_c_entry"

    def test_header_file_no_entry(self):
        source = """\
int helper(void);
"""
        entries = self._detect_entries(source, file_name="include/helper.h")
        # No main in header, and default only matches .c pattern
        assert len(entries) == 0

    def test_or_pattern(self):
        source = """\
int main(int argc, char *argv[]) {
    return 0;
}
"""
        rules = [{
            "name": "multi_entry",
            "file_pattern": "**/*.c",
            "ast_pattern": "function_def:main | function_def:WinMain",
            "enabled": True,
        }]
        entries = self._detect_entries(source, rules)
        main_entries = [e for e in entries if e.rule_name == "multi_entry"]
        assert len(main_entries) >= 1

    def test_winmain_detected(self):
        source = """\
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                   LPSTR lpCmdLine, int nCmdShow) {
    return 0;
}
"""
        rules = [{
            "name": "c_main",
            "file_pattern": "**/*.c",
            "ast_pattern": (
                "function_def:main | function_def:WinMain | "
                "function_def:wWinMain | function_def:DllMain | "
                "function_def:_tmain"
            ),
            "enabled": True,
        }]
        entries = self._detect_entries(source, rules)
        assert any(e.rule_name == "c_main" for e in entries)

    def test_c_test_file_entry(self):
        source = "int main(void) { return 0; }\n"
        rules = [{
            "name": "c_test",
            "file_pattern": "**/*.c",
            "ast_pattern": "test_file",
            "enabled": True,
            "no_propagate": True,
        }]
        entries = self._detect_entries(source, rules, file_name="test_foo.c")
        test_entries = [e for e in entries if e.rule_name == "c_test"]
        assert len(test_entries) == 1
        assert test_entries[0].no_propagate is True

    def test_c_test_file_suffix_entry(self):
        source = "int main(void) { return 0; }\n"
        rules = [{
            "name": "c_test",
            "file_pattern": "**/*.c",
            "ast_pattern": "test_file",
            "enabled": True,
            "no_propagate": True,
        }]
        entries = self._detect_entries(source, rules, file_name="foo_test.c")
        test_entries = [e for e in entries if e.rule_name == "c_test"]
        assert len(test_entries) == 1

    def test_c_test_non_test_file_no_entry(self):
        source = "int main(void) { return 0; }\n"
        rules = [{
            "name": "c_test",
            "file_pattern": "**/*.c",
            "ast_pattern": "test_file",
            "enabled": True,
            "no_propagate": True,
        }]
        entries = self._detect_entries(source, rules, file_name="src/main.c")
        test_entries = [e for e in entries if e.rule_name == "c_test"]
        assert test_entries == []

    def test_c_test_file_entry_line_zero(self):
        source = (
            "int first_fn(void) { return 0; }\n"
            "int second_fn(void) { return 0; }\n"
        )
        rules = [{
            "name": "c_test",
            "file_pattern": "**/*.c",
            "ast_pattern": "test_file",
            "enabled": True,
            "no_propagate": True,
        }]
        entries = self._detect_entries(source, rules, file_name="test_foo.c")
        test_entries = [e for e in entries if e.rule_name == "c_test"]
        assert len(test_entries) == 1
        assert test_entries[0].line == 0
        assert test_entries[0].no_propagate is True


# =============================================================================
# End-to-end reachability tests
# =============================================================================


def _dead_nodes(br: GraphBuildResult) -> set[str]:
    """Compute dead node qualified names from the graph build result."""
    nid_map = br.node_id_map
    all_ids = set(nid_map.keys())
    dead_ids = all_ids - br.reachable
    return {nid_map[n].qualified_name for n in dead_ids if n in nid_map}


def _live_nodes(br: GraphBuildResult) -> set[str]:
    """Compute live node qualified names from the graph build result."""
    nid_map = br.node_id_map
    return {nid_map[n].qualified_name for n in br.reachable if n in nid_map}


@tree_sitter_available
class TestCEndToEnd:
    """End-to-end tests: parse, build graph, detect dead code."""

    def _build(self, files: dict[str, str]) -> tuple[GraphBuildResult, WarningCollector]:
        import tempfile
        from graphlint.analyzer.graph import GraphBuilder
        from graphlint.analyzer.warnings import WarningCollector
        from graphlint.api import _build_registry
        from graphlint.config.manager import ConfigManager

        tmp = tempfile.mkdtemp()
        for rel, content in files.items():
            full = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(content)
        config = ConfigManager(tmp).load()
        config["_root_dir"] = tmp
        config.setdefault("entry_rules", [
            {
                "name": "c_main",
                "file_pattern": "**/*.c",
                "ast_pattern": "function_def:main",
                "enabled": True,
                "description": "C main() program entry point",
            },
        ])
        registry = _build_registry()
        adapter = registry.adapter_for_file("x.c")
        prs = {}
        for root, _d, fns in os.walk(tmp):
            for fn in fns:
                if fn.endswith(".c") or fn.endswith(".h"):
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, tmp).replace(os.sep, "/")
                    prs[rel] = adapter.parse_file(full, tmp, config)
        wb = WarningCollector()
        gb = GraphBuilder(wb, registry=registry, config=config)
        return gb.build(prs), wb

    def test_simple_reachability(self):
        br, wb = self._build({
            "src/main.c": (
                'int helper(void) { return 42; }\n'
                'int main(void) { return helper(); }\n'
            ),
        })
        live = _live_nodes(br)
        assert "src.main.helper" in live, live
        assert "src.main.main" in live, live

    def test_dead_function_detected(self):
        br, wb = self._build({
            "src/main.c": (
                'int helper(void) { return 42; }\n'
                'int dead_func(void) { return 0; }\n'
                'int main(void) { return helper(); }\n'
            ),
        })
        dead = _dead_nodes(br)
        assert "src.main.dead_func" in dead, dead

    def test_reachable_through_call_chain(self):
        br, wb = self._build({
            "src/a.c": (
                'int calc(void) { return 100; }\n'
            ),
            "src/main.c": (
                'int calc(void);\n'
                'int middle(void) { return calc(); }\n'
                'int main(void) { return middle(); }\n'
            ),
        })
        live = _live_nodes(br)
        assert "src.a.calc" in live, live
        assert "src.main.middle" in live, live
        assert "src.main.main" in live, live

    def test_global_variable_reachable(self):
        br, wb = self._build({
            "src/main.c": (
                'int counter = 0;\n'
                'int main(void) { counter = 1; return 0; }\n'
            ),
        })
        live = _live_nodes(br)
        assert "src.main.counter" in live, live

    def test_struct_reachable_via_usage(self):
        br, wb = self._build({
            "src/main.c": (
                'struct Point { int x; int y; };\n'
                'int main(void) {\n'
                '    struct Point p = {1, 2};\n'
                '    return p.x;\n'
                '}\n'
            ),
        })
        live = _live_nodes(br)
        assert "src.main.Point" in live, live

    def test_multi_file_dead_code(self):
        br, wb = self._build({
            "src/util.c": (
                'int useful(void) { return 1; }\n'
                'int useless(void) { return 0; }\n'
            ),
            "src/main.c": (
                'int useful(void);\n'
                'int main(void) { return useful(); }\n'
            ),
        })
        live = _live_nodes(br)
        assert "src.util.useful" in live, live
        assert "src.util.useless" not in live

    def test_anonymous_struct_in_function_keeps_callee_live(self):
        br, wb = self._build({
            "src/main.c": (
                'int helper(void) { return 42; }\n'
                'void f(void) { struct { int a; } s; helper(); }\n'
                'int main(void) { f(); return 0; }\n'
            ),
        })
        live = _live_nodes(br)
        assert "src.main.helper" in live, live
        assert "src.main.f" in live, live

    def test_fnodes_map_prefers_function_on_qname_collision(self):
        br, wb = self._build({
            "src/main.c": (
                'int helper(void) { return 42; }\n'
                'int f(void) { return helper(); }\n'
                'typedef struct { int x; } f;\n'
                'int main(void) { return f(); }\n'
            ),
        })
        nid_map = br.node_id_map
        f_func = next(
            n for n in nid_map.values()
            if n.qualified_name == "src.main.f" and n.node_type == "function"
        )
        helper = next(
            n for n in nid_map.values()
            if n.qualified_name == "src.main.helper" and n.node_type == "function"
        )
        helper_in_edges = [e for e in br.edges if e.target_id == helper.id]
        assert helper_in_edges, "helper should have an incoming edge"
        assert any(e.source_id == f_func.id for e in helper_in_edges), (
            "helper's in-edge must be sourced from function f, not the typedef"
        )

    # --- regression tests for TODO #3/#4/#5 and the FP fixes -------------

    def test_enum_used_only_via_constant_is_live(self):
        br, wb = self._build({
            "src/main.c": (
                'enum Color { RED, GREEN };\n'
                'int main(void) { return RED; }\n'
            ),
        })
        live = _live_nodes(br)
        dead = _dead_nodes(br)
        assert "src.main.Color" in live, live
        assert "src.main.Color.RED" in live, live
        # Unused enum constants are genuinely dead.
        assert "src.main.Color.GREEN" in dead, dead

    def test_mixed_declarator_variable_is_live(self):
        br, wb = self._build({
            "src/main.c": (
                'int foo(void), bar;\n'
                'int main(void) { bar = 1; return bar; }\n'
            ),
        })
        live = _live_nodes(br)
        assert "src.main.bar" in live, live

    def test_include_guard_macro_live_when_header_used(self):
        br, wb = self._build({
            "src/helper.h": (
                '#ifndef HELPER_H\n'
                '#define HELPER_H\n'
                'int helper(void);\n'
                '#endif\n'
            ),
            "src/helper.c": (
                '#include "helper.h"\n'
                'int helper(void) { return 42; }\n'
            ),
            "src/main.c": (
                '#include "helper.h"\n'
                'int main(void) { return helper(); }\n'
            ),
        })
        live = _live_nodes(br)
        assert "src.helper.HELPER_H" in live, live

    def test_unused_macro_still_dead(self):
        br, wb = self._build({
            "src/main.c": (
                '#define UNUSED 1\n'
                'int main(void) { return 0; }\n'
            ),
        })
        dead = _dead_nodes(br)
        assert "src.main.UNUSED" in dead, dead

    def test_macro_used_in_live_function_is_live(self):
        br, wb = self._build({
            "src/main.c": (
                '#define LIMIT 100\n'
                'int main(void) { return LIMIT; }\n'
            ),
        })
        live = _live_nodes(br)
        assert "src.main.LIMIT" in live, live

    def test_typedef_used_in_live_code_is_live(self):
        br, wb = self._build({
            "src/main.c": (
                'typedef struct { int x; } Item;\n'
                'int main(void) { Item it = {1}; return it.x; }\n'
            ),
        })
        live = _live_nodes(br)
        assert "src.main.Item" in live, live

    def test_union_used_in_live_code_is_live(self):
        br, wb = self._build({
            "src/main.c": (
                'union Data { int i; float f; };\n'
                'int main(void) { union Data d; d.i = 1; return d.i; }\n'
            ),
        })
        live = _live_nodes(br)
        assert "src.main.Data" in live, live

    def test_typedef_used_only_as_field_type_is_live(self):
        br, wb = self._build({
            "src/main.c": (
                'typedef struct { int x; } Item;\n'
                'struct Holder { Item item; };\n'
                'int main(void) { struct Holder h; return h.item.x; }\n'
            ),
        })
        live = _live_nodes(br)
        assert "src.main.Item" in live, live

    def test_dead_file_typedef_not_promoted_via_live_component(self):
        # Regression: a dead file's typedef must stay dead even when the
        # component it sits in (via cross-file read edges) has live seeds.
        br, wb = self._build({
            "src/main.c": (
                'int gv;\n'
                'int main(void) { gv = 1; return gv; }\n'
            ),
            "src/b.c": (
                'typedef struct { int y; } BItem;\n'
                'BItem bg;\n'
                'void useb(void) { BItem x; x.y = gv; }\n'
            ),
        })
        dead = _dead_nodes(br)
        live = _live_nodes(br)
        assert "src.b.BItem" in dead, dead
        assert "src.b.useb" in dead, dead
        assert "src.b.bg" in dead, dead
        assert "src.main.gv" in live, live
