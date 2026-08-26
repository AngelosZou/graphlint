# -*- coding: utf-8 -*-
"""Tests for content-based ``.h`` header routing (sniff helper + registry).

These assert the routing *decision* only — no C/C++ parse required.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from graphlint.analyzer.language.registry import LanguageRegistry, sniff_header_language
from graphlint.analyzer.language.c import CAdapter
from graphlint.analyzer.language.cpp import CppAdapter
from graphlint.analyzer.language.cpp.constants import _TREE_SITTER_CPP_AVAILABLE


def _write_header(text: str, suffix: str = ".h") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


# =============================================================================
# sniff_header_language
# =============================================================================


class TestSniff:
    def test_sniff_class_cpp(self):
        path = _write_header("class F {\npublic:\n    void m() {}\n};\n")
        assert sniff_header_language(path) == "cpp"

    def test_sniff_namespace_cpp(self):
        path = _write_header("namespace foo { }\n")
        assert sniff_header_language(path) == "cpp"

    def test_sniff_template_cpp(self):
        path = _write_header("template<typename T>\nT add(T a, T b) { return a + b; }\n")
        assert sniff_header_language(path) == "cpp"

    def test_sniff_std_cpp(self):
        path = _write_header("#include <iostream>\nusing std::cout;\n")
        assert sniff_header_language(path) == "cpp"

    def test_sniff_plain_c(self):
        path = _write_header("#include <stdio.h>\nstruct S { int x; };\n")
        assert sniff_header_language(path) == "c"

    def test_sniff_plain_c_stdin_h(self):
        path = _write_header("#include <string.h>\nint f(char *s) { return 0; }\n")
        assert sniff_header_language(path) == "c"

    def test_sniff_empty_or_default_c(self):
        path = _write_header("")
        assert sniff_header_language(path) == "c"
        path2 = _write_header("typedef struct { int a; } Widget;\n")
        assert sniff_header_language(path2) == "c"

    def test_sniff_comment_not_tricked(self):
        line = _write_header("// class Foo { }\nint x;\n")
        assert sniff_header_language(line) == "c"
        block = _write_header("/* namespace bar { } */\nint x;\n")
        assert sniff_header_language(block) == "c"

    def test_sniff_missing_file_default_c(self):
        assert sniff_header_language("/no/such/header.h") == "c"

    def test_sniff_string_literal_not_tricked(self):
        """A C++ marker inside a string literal (shader/doc/JSON-template
        name) must not route a plain-C header to C++."""
        for body in (
            'const char* s = "class Foo";',
            'const char* s = "std::vector";',
            'const char* n = "namespace x";',
        ):
            path = _write_header(body + "\nint x;\n")
            assert sniff_header_language(path) == "c", body

    def test_sniff_string_literal_include_not_signal(self):
        """A ``#include <vector>`` inside a string literal is not a directive."""
        path = _write_header('const char* e = "#include <vector>";\n')
        assert sniff_header_language(path) == "c"

    def test_sniff_operator_identifier_not_cpp(self):
        """``operator`` is a legal C identifier/field, so a bare ``operator``
        must not be treated as a C++ operator-overload signal."""
        for body in (
            "int operator;",
            "struct S { int operator; };",
        ):
            path = _write_header(body + "\n")
            assert sniff_header_language(path) == "c", body

    def test_sniff_operator_overload_still_detected_via_class(self):
        """A C++ operator overload retains a C++ signal through the enclosing
        class, so the removed ``operator`` marker does not lose it."""
        path = _write_header(
            "class Vec { public: bool operator==(const Vec&) const; };\n"
        )
        assert sniff_header_language(path) == "cpp"


# =============================================================================
# Registry routing (extension vs content)
# =============================================================================


class TestRegistryRouting:
    def _registry(self) -> LanguageRegistry:
        reg = LanguageRegistry()
        reg.register(CAdapter())
        reg.register(CppAdapter())
        return reg

    def test_hpp_not_sniffed_by_ext(self):
        """x.hpp routes by extension to the C++ adapter, never sniffed."""
        reg = self._registry()
        path = _write_header("int plain_c_looking_thing(void);\n", suffix=".hpp")
        adapter = reg.adapter_for_parsing(path)
        assert adapter is not None
        assert adapter.language_name == "cpp"

    @pytest.mark.skipif(not hasattr(CppAdapter, "language_name"), reason="no cpp")
    def test_h_class_sniffed_cpp(self):
        reg = self._registry()
        path = _write_header("class F {\npublic:\n    void m() {}\n};\n")
        adapter = reg.adapter_for_parsing(path)
        assert adapter.language_name == "cpp"

    def test_h_plain_stays_c(self):
        reg = self._registry()
        path = _write_header("#include <stdio.h>\nstruct S { int x; };\n")
        adapter = reg.adapter_for_parsing(path)
        assert adapter.language_name == "c"

    def test_cpp_extension_unchanged(self):
        reg = self._registry()
        assert reg.adapter_for_parsing("x.cpp").language_name == "cpp"
        assert reg.adapter_for_parsing("x.c").language_name == "c"


# =============================================================================
# End-to-end: a ``.h`` sniffed as C++ is actually parsed by the C++ backend.
# Parity with the owner symptom (``class Engine {...}`` in a ``.h``).
# =============================================================================


@pytest.mark.skipif(
    not _TREE_SITTER_CPP_AVAILABLE, reason="tree-sitter-cpp not installed"
)
class TestSniffParsesHeader:
    def test_class_in_h_parsed_as_cpp(self):
        """A ``.h`` containing ``class F { }`` routes to the C++ backend and
        produces a class node (no corruption, no syntax_error)."""
        from graphlint.analyzer._types import ParseResult

        reg = LanguageRegistry()
        reg.register(CAdapter())
        reg.register(CppAdapter())

        root = tempfile.mkdtemp()
        src = os.path.join(root, "engine.h")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(
                "class Engine {\n"
                "public:\n"
                "    void start() {}\n"
                "    void stop() {}\n"
                "};\n"
            )

        adapter = reg.adapter_for_parsing(src)
        assert adapter.language_name == "cpp"
        result: ParseResult = adapter.worker_function(src, root, {})
        assert not any(
            w.warn_type == "syntax_error" or "parse_error" in str(w.warn_type)
            for w in result.warnings
        ), result.warnings
        class_nodes = [n for n in result.nodes if n.node_type == "class"]
        assert any("Engine" in (n.name or "") for n in class_nodes), [
            n.name for n in result.nodes
        ]

    def test_plain_c_h_parsed_as_c(self):
        """A plain-C ``.h`` routes to the C backend and parses cleanly."""
        from graphlint.analyzer._types import ParseResult

        reg = LanguageRegistry()
        reg.register(CAdapter())
        reg.register(CppAdapter())

        root = tempfile.mkdtemp()
        src = os.path.join(root, "point.h")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write("#include <stdio.h>\nstruct Point { int x; int y; };\n")

        adapter = reg.adapter_for_parsing(src)
        assert adapter.language_name == "c"
        result: ParseResult = adapter.worker_function(src, root, {})
        assert not any(
            w.warn_type == "syntax_error" or "parse_error" in str(w.warn_type)
            for w in result.warnings
        ), result.warnings
        struct_nodes = [n for n in result.nodes if n.node_type == "struct"]
        assert any("Point" in (n.name or "") for n in struct_nodes), [
            n.name for n in result.nodes
        ]

# =============================================================================
# comment-embedded C++ include signals must NOT trip the C++ route
# =============================================================================


class TestSniffCommentSafety:
    def test_line_comment_include_not_signal(self):
        """A ``// #include <vector>`` inside a line comment stays on the C route."""
        path = _write_header("// #include <vector>\nint x;\n")
        assert sniff_header_language(path) == "c"

    def test_block_comment_include_not_signal(self):
        """A ``/* #include <vector> */`` inside a block comment stays on the C route."""
        path = _write_header("/* #include <vector> */\nint x;\n")
        assert sniff_header_language(path) == "c"

    def test_real_include_signals_cpp(self):
        """A real ``#include <vector>`` directive signals C++ (and is preserved)."""
        path = _write_header("#include <vector>\nint f();\n")
        assert sniff_header_language(path) == "cpp"

    def test_real_include_hpp_signals_cpp(self):
        path = _write_header("#include \"util.hpp\"\nint f();\n")
        assert sniff_header_language(path) == "cpp"
