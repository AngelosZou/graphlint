# -*- coding: utf-8 -*-
"""Tests for the C++ language adapter."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest

from graphlint.analyzer.language.cpp.constants import (
    _CPP_PUBLIC_API_NAMES,
    _CPP_SPECIAL_NAMES,
    _TREE_SITTER_CPP_AVAILABLE,
    _file_to_module,
    _is_test_file,
)
from graphlint.analyzer.language.cpp.imports import CppImportAnalyzer
from graphlint.analyzer.language.cpp.visitor import CppVisitor


tree_sitter_available = pytest.mark.skipif(
    not _TREE_SITTER_CPP_AVAILABLE, reason="tree-sitter-cpp not installed"
)


# =============================================================================
# Constants tests (always runnable)
# =============================================================================


class TestCppConstants:
    def test_file_to_module(self):
        assert _file_to_module("src/Player.cpp") == "src.Player"
        assert _file_to_module("src/tools/util.cc") == "src.tools.util"
        assert _file_to_module("include/Entity.hpp") == "include.Entity"
        assert _file_to_module("runner.py") == ""

    def test_special_names(self):
        assert "CLASS_NAME" in _CPP_SPECIAL_NAMES
        assert "~CLASS_NAME" in _CPP_SPECIAL_NAMES
        assert "operator=" in _CPP_SPECIAL_NAMES
        assert "operator()" in _CPP_SPECIAL_NAMES

    def test_public_api_names(self):
        assert "main" in _CPP_PUBLIC_API_NAMES

    def test_is_test_file_dir_patterns(self):
        config = {}
        assert _is_test_file("tests/test_main.cpp", config) is True
        assert _is_test_file("test/test_thing.cpp", config) is True
        assert _is_test_file("Tests/suite.cpp", config) is True
        assert _is_test_file("src/main.cpp", config) is False

    def test_is_test_file_name_patterns(self):
        config = {}
        assert _is_test_file("my_test.cpp", config) is True
        assert _is_test_file("my_tests.cpp", config) is True
        assert _is_test_file("test_utils.cpp", config) is True
        assert _is_test_file("game.cpp", config) is False


# =============================================================================
# Adapter registration tests (always runnable)
# =============================================================================


class TestCppAdapterRegistration:
    def test_adapter_imports_gracefully(self):
        from graphlint.analyzer.language.cpp import CppAdapter
        adapter = CppAdapter()
        assert adapter.language_name == "cpp"
        assert ".cpp" in adapter.file_extensions
        assert ".hpp" in adapter.file_extensions
        assert adapter.is_special_name("CLASS_NAME") is True
        assert adapter.is_special_name("main") is False

    def test_registry_skips_cpp_gracefully(self):
        from graphlint.api import _build_registry
        registry = _build_registry()
        adapter = registry.adapter_for_file("test.cpp")
        if _TREE_SITTER_CPP_AVAILABLE:
            assert adapter is not None
        else:
            assert adapter is None

    def test_worker_function_pickleable(self):
        from graphlint.analyzer.language.cpp import CppAdapter
        adapter = CppAdapter()
        assert adapter.worker_function is not None
        import pickle
        # Worker function must be picklable (module-level)
        pickle.dumps(adapter.worker_function)


# =============================================================================
# Visitor tests (require tree-sitter-cpp)
# =============================================================================


def _parse_source(source: str, module_qname: str = "test", file_path: str = "test.cpp") -> CppVisitor:
    """Parse *source* into a :class:`CppVisitor`."""
    import tree_sitter
    from graphlint.analyzer.language.cpp.constants import _get_cpp_language

    lang = _get_cpp_language()
    parser = tree_sitter.Parser()
    if hasattr(parser, "set_language"):
        parser.set_language(lang)
    else:
        parser.language = lang
    tree = parser.parse(source.encode("utf-8"))

    import_analyzer = CppImportAnalyzer()
    visitor = CppVisitor(module_qname, file_path, import_analyzer)
    visitor.visit(tree)
    return visitor


@tree_sitter_available
class TestCppVisitorBasic:
    """Basic CST visitor tests — simple C++ parsing."""

    def test_simple_class_with_method(self):
        source = """\
class Player {
public:
    int getHealth() const { return health; }
private:
    int health;
};
"""
        visitor = _parse_source(source)
        nodes = visitor.nodes

        class_nodes = [n for n in nodes if n.node_type == "class"]
        assert len(class_nodes) == 1
        assert class_nodes[0].name == "Player"

        method_nodes = [n for n in nodes if n.node_type == "method"]
        assert len(method_nodes) == 1
        assert method_nodes[0].name == "getHealth"

        field_nodes = [n for n in nodes if n.node_type == "field"]
        assert len(field_nodes) == 1
        assert field_nodes[0].name == "health"

    def test_top_level_function(self):
        source = """\
#include <iostream>

void sayHello() {
    std::cout << "Hello" << std::endl;
}
"""
        visitor = _parse_source(source)
        funcs = [n for n in visitor.nodes if n.node_type == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "sayHello"

    def test_struct_is_class_type(self):
        source = """\
struct Point {
    int x;
    int y;
};
"""
        visitor = _parse_source(source)
        structs = [n for n in visitor.nodes if n.node_type == "struct"]
        assert len(structs) == 1
        assert structs[0].name == "Point"

        fields = [n for n in visitor.nodes if n.node_type == "field"]
        assert len(fields) == 2
        assert fields[0].name == "x"
        assert fields[1].name == "y"

    def test_enum(self):
        source = """\
enum Color { Red, Green, Blue };
"""
        visitor = _parse_source(source)
        enums = [n for n in visitor.nodes if n.node_type == "enum"]
        assert len(enums) == 1
        assert enums[0].name == "Color"

    def test_macro(self):
        source = """\
#define MAX_SIZE 100
#define SQUARE(x) ((x)*(x))
"""
        visitor = _parse_source(source)
        macros = [n for n in visitor.nodes if n.node_type == "macro"]
        assert len(macros) == 2
        assert macros[0].name == "MAX_SIZE"
        assert macros[1].name == "SQUARE"

    def test_variable_declaration(self):
        source = """\
int counter = 0;
void main() {
    int x = 5;
}
"""
        visitor = _parse_source(source)
        variables = [n for n in visitor.nodes if n.node_type == "variable"]
        assert len(variables) == 2
        assert variables[0].name == "counter"
        assert variables[1].name == "x"

    def test_template_function(self):
        source = """\
template<typename T>
T max_of(T a, T b) {
    return (a > b) ? a : b;
}
"""
        visitor = _parse_source(source)
        funcs = [n for n in visitor.nodes if n.node_type == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "max_of"

    def test_operator_overload(self):
        source = """\
class Vector {
public:
    Vector operator+(const Vector& other) const {
        return Vector();
    }
};
"""
        visitor = _parse_source(source)
        methods = [n for n in visitor.nodes if n.node_type == "method"]
        assert len(methods) == 1
        assert methods[0].name == "operator+"


@tree_sitter_available
class TestCppInheritance:
    """Tests for inheritance edges and parent-method resolution."""

    def test_inheritance_edge(self):
        source = """\
class Entity {
public:
    int getHealth() const { return 100; }
};

class Player : public Entity {
public:
    void update() { }
};
"""
        visitor = _parse_source(source)
        refs = visitor.references

        inherit_edges = [r for r in refs if r.edge_type == "inherit"]
        assert len(inherit_edges) == 1
        assert inherit_edges[0].target_name == "Entity"

    def test_multiple_inheritance(self):
        source = """\
class Drawable { };
class Movable { };
class Player : public Drawable, public Movable { };
"""
        visitor = _parse_source(source)
        refs = visitor.references

        inherit_edges = [r for r in refs if r.edge_type == "inherit"]
        assert len(inherit_edges) == 2


@tree_sitter_available
class TestCppMemberCallResolution:
    """Approach A: static member-call resolution."""

    def test_member_call_resolves_to_method(self):
        """player.update() should resolve to Player::update."""
        source = """\
class Player {
public:
    void update() { }
};

int main() {
    Player player;
    player.update();
    return 0;
}
"""
        visitor = _parse_source(source)
        refs = visitor.references

        # Check that player.update() produces a call edge
        call_edges = [r for r in refs if r.edge_type == "call" and "update" in r.target_name]
        assert len(call_edges) >= 1, call_edges

    def test_unknown_receiver_conservative_read(self):
        """x.unknown() with unknown receiver type → conservative read edge."""
        source = """\
void foo(void* ptr) {
    // ptr is void*, method unknown
}
"""
        visitor = _parse_source(source)
        # Should not crash, and should not emit specious call edges
        refs = visitor.references
        # void* has no known type — nothing to resolve
        assert all(r.edge_type != "call" or "unknown" not in r.target_name
                   for r in refs)

    def test_std_receiver_conservative(self):
        """std::cout << → conservative, no error."""
        source = """\
#include <iostream>
int main() {
    std::cout << "Hello" << std::endl;
    return 0;
}
"""
        visitor = _parse_source(source)
        # Should not crash, std:: names should not produce call edges
        # (they are treated conservatively)
        for r in visitor.references:
            if r.edge_type == "call":
                # call edges should be to known names only
                assert not r.target_name.startswith("std::")

    def test_member_call_on_field_type(self):
        """Field declarations propagate types for receiver resolution."""
        source = """\
class Engine {
public:
    void start() { }
};

class Car {
public:
    Engine engine;
    void go() {
        engine.start();
    }
};
"""
        visitor = _parse_source(source)
        refs = visitor.references

        call_edges = [r for r in refs if r.edge_type == "call" and "start" in r.target_name]
        assert len(call_edges) >= 1, call_edges


@tree_sitter_available
class TestCppIncludes:
    """Tests for #include analysis."""

    def test_system_include_skipped(self):
        source = """\
#include <iostream>
#include <vector>
int main() { return 0; }
"""
        visitor = _parse_source(source)
        # System includes are skipped
        local_includes = [u for u in visitor.uses if not u.is_system]
        assert len(local_includes) == 0
        system_includes = [u for u in visitor.uses if u.is_system]
        assert len(system_includes) == 0  # Both are system includes, skipped entirely

    def test_local_include_recorded(self):
        source = """\
#include "Player.h"
#include "utils/helpers.h"
int main() { return 0; }
"""
        visitor = _parse_source(source)
        local = [u for u in visitor.uses if not u.is_system]
        assert len(local) == 2
        assert local[0].include_path == "Player.h"
        assert local[1].include_path == "utils/helpers.h"

    def test_mixed_includes(self):
        source = """\
#include <string>
#include "Entity.hpp"
#include <algorithm>
"""
        visitor = _parse_source(source)
        local = [u for u in visitor.uses if not u.is_system]
        assert len(local) == 1
        assert local[0].include_path == "Entity.hpp"


@tree_sitter_available
class TestCppCallEdges:
    """Tests for call expression edges."""

    def test_free_function_call(self):
        source = """\
void helper() { }

int main() {
    helper();
    return 0;
}
"""
        visitor = _parse_source(source)
        refs = visitor.references

        calls = [r for r in refs if r.edge_type == "call" and r.target_name == "helper"]
        assert len(calls) >= 1

    def test_namespace_qualified_call(self):
        source = """\
namespace utils {
    void log(const char* msg) { }
}

int main() {
    utils::log("hello");
    return 0;
}
"""
        visitor = _parse_source(source)
        refs = visitor.references

        calls = [r for r in refs if r.edge_type == "call" and "log" in r.target_name]
        assert len(calls) >= 1

    def test_new_expression_read_edge(self):
        source = """\
class Widget { };

int main() {
    Widget* w = new Widget();
    return 0;
}
"""
        visitor = _parse_source(source)
        refs = visitor.references

        reads = [r for r in refs if r.edge_type == "read" and r.target_name == "Widget"]
        assert len(reads) >= 1


@tree_sitter_available
class TestCppEndToEnd:
    """End-to-end dead code detection tests."""

    def _build(self, files: dict[str, str]) -> Any:
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
        registry = _build_registry()
        adapter = registry.adapter_for_file("x.cpp")
        assert adapter is not None, "C++ adapter not registered"

        prs = {}
        for root, _d, fns in os.walk(tmp):
            for fn in fns:
                if any(fn.endswith(ext) for ext in (".cpp", ".cc", ".cxx",
                                                      ".hpp", ".hh", ".hxx")):
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, tmp).replace(os.sep, "/")
                    prs[rel] = adapter.parse_file(full, tmp, config)

        wb = WarningCollector()
        gb = GraphBuilder(wb, registry=registry, config=config)
        return gb.build(prs), wb

    def test_main_chain_live_uncalled_dead(self):
        """Main → live chain reachable; uncalled method dead."""
        br, wb = self._build({
            "src/main.cpp": (
                "class Player {\n"
                "public:\n"
                "    void usedMethod() { }\n"
                "    void deadMethod() { }\n"
                "};\n"
                "int main() {\n"
                "    Player p;\n"
                "    p.usedMethod();\n"
                "    return 0;\n"
                "}\n"
            ),
        })
        nid_map = br.node_id_map
        live = {nid_map[n].qualified_name for n in br.reachable if n in nid_map}

        assert "src.main.Player" in live, live
        assert "src.main.Player.usedMethod" in live, live
        assert "src.main.Player.deadMethod" not in live, live

    def test_uncalled_free_function_dead(self):
        """Free function not called from main is dead."""
        br, wb = self._build({
            "src/main.cpp": (
                "void dead_function() { }\n"
                "int main() { return 0; }\n"
            ),
        })
        nid_map = br.node_id_map
        live = {nid_map[n].qualified_name for n in br.reachable if n in nid_map}

        assert "src.main.dead_function" not in live, live

    def test_inherited_method_reachable(self):
        """Child instance can reach parent method."""
        br, wb = self._build({
            "src/main.cpp": (
                "class Entity {\n"
                "public:\n"
                "    int getHealth() const { return 100; }\n"
                "};\n"
                "class Player : public Entity {\n"
                "public:\n"
                "    void update() { }\n"
                "};\n"
                "int main() {\n"
                "    Player p;\n"
                "    p.getHealth();\n"
                "    return 0;\n"
                "}\n"
            ),
        })
        nid_map = br.node_id_map
        live = {nid_map[n].qualified_name for n in br.reachable if n in nid_map}

        # Entity should be reachable via Player's inheritance
        assert "src.main.Entity" in live, live
        assert "src.main.Entity.getHealth" in live, live
        assert "src.main.Player" in live, live

    def test_std_cout_no_noise(self):
        """std::cout/std::endl should not produce dead_code warnings."""
        br, wb = self._build({
            "src/main.cpp": (
                "#include <iostream>\n"
                "int main() {\n"
                "    std::cout << \"Hello\" << std::endl;\n"
                "    return 0;\n"
                "}\n"
            ),
        })
        nid_map = br.node_id_map
        live = {nid_map[n].qualified_name for n in br.reachable if n in nid_map}

        # main should be live
        assert "src.main.main" in live, live

        # No dead_code warnings from std:: names
        dead_warns = [w for w in wb.get_all() if w.warn_type == "dead_code"]
        for w in dead_warns:
            if w.node_id in nid_map:
                qn = nid_map[w.node_id].qualified_name
                assert "std" not in qn, f"false dead_code on std symbol: {qn}"


@tree_sitter_available
class TestCppConstructorDestructor:
    """Tests for constructor and destructor handling."""

    def test_constructor_detected_as_method(self):
        source = """\
class Service {
public:
    Service() { }
};
"""
        visitor = _parse_source(source)
        methods = [n for n in visitor.nodes if n.node_type == "method"]
        assert len(methods) == 1

    def test_destructor(self):
        source = """\
class Service {
public:
    ~Service() { }
};
"""
        visitor = _parse_source(source)
        methods = [n for n in visitor.nodes if n.node_type == "method"]
        assert len(methods) == 1
        # Destructor keeps its real class name (not a shared placeholder).
        assert methods[0].name == "~Service"


@tree_sitter_available
class TestCppQualifiedNames:
    """Tests for namespace and nested scoping."""

    def test_namespace_scoped_qualified_name(self):
        source = """\
namespace game {
    class Player {
    public:
        void update() { }
    };
}
"""
        visitor = _parse_source(source)
        nodes = visitor.nodes

        class_nodes = [n for n in nodes if n.node_type == "class"]
        assert len(class_nodes) == 1
        assert class_nodes[0].qualified_name == "test.game.Player"

        method_nodes = [n for n in nodes if n.node_type == "method"]
        assert len(method_nodes) == 1
        assert method_nodes[0].qualified_name == "test.game.Player.update"


@tree_sitter_available
class TestCppMethodDeclarationSkipped:
    """Method declarations without bodies should not produce nodes."""

    def test_declaration_only_no_node(self):
        source = """\
class Interface {
public:
    virtual void render() = 0;
    virtual void update(float dt);
};
"""
        visitor = _parse_source(source)
        methods = [n for n in visitor.nodes if n.node_type == "method"]
        # Pure virtual and declaration-only methods have no body → no node
        assert len(methods) == 0


@tree_sitter_available
class TestCppParserIntegration:
    """Tests for the CppSourceParser orchestration."""

    def test_parser_produces_nodes(self):
        """Full parse should produce nodes, references, imports."""
        import tempfile

        from graphlint.analyzer.language.cpp.parser import CppSourceParser

        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "main.cpp")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write("""\
#include "Player.h"

class Player {
public:
    int getHealth() const { return 100; }
};
""")

        parser = CppSourceParser(tmp, {})
        result = parser.parse_file(src)
        assert result.file_path == "main.cpp"
        assert len(result.nodes) >= 2  # Player class + getHealth method
        # At least one local include
        imports = [i for i in result.imports]
        assert len(imports) >= 1
        assert imports[0].include_path == "Player.h"
        assert imports[0].is_system is False

    def test_parser_handles_missing_file(self):
        import tempfile

        from graphlint.analyzer.language.cpp.parser import CppSourceParser

        tmp = tempfile.mkdtemp()
        parser = CppSourceParser(tmp, {})
        result = parser.parse_file(os.path.join(tmp, "no_such_file.cpp"))
        assert len(result.warnings) >= 1
        any_w = any("parse_error" in str(w) for w in result.warnings)
        assert any_w or len(result.warnings) > 0


@tree_sitter_available
class TestCppEntryDetection:
    """Tests for C++ entry point detection."""

    def test_main_detected_as_entry(self):
        """main() function should match the cpp_main rule."""
        from graphlint.analyzer.language.cpp.entry import CppEntryPointDetector
        from graphlint.analyzer.language.cpp.parser import CppSourceParser

        source = """\
int main() {
    return 0;
}
"""
        import tempfile
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "main.cpp")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(source)

        config = {
            "entry_rules": [
                {
                    "name": "cpp_main",
                    "file_pattern": "**/*.{cpp,cc,cxx,c,hpp,hh,hxx,h}",
                    "ast_pattern": "function_def:main",
                    "enabled": True,
                    "description": "C++ main() entry point",
                },
            ],
        }
        pr = CppSourceParser(tmp, config).parse_file(src)
        detector = CppEntryPointDetector(config)
        entries = detector.detect({"main.cpp": pr}, pr.nodes, {})
        cpp_main = [e for e in entries if e.rule_name == "cpp_main"]
        assert len(cpp_main) >= 1

    def _entry_config(self):
        return {
            "entry_rules": [
                {
                    "name": "cpp_main",
                    "file_pattern": "**/*.{cpp,cc,cxx,c,hpp,hh,hxx,h}",
                    "ast_pattern": "function_def:main",
                    "enabled": True,
                    "description": "C++ main() entry point",
                },
            ],
        }

    def _detect(self, source):
        from graphlint.analyzer.language.cpp.entry import CppEntryPointDetector
        from graphlint.analyzer.language.cpp.parser import CppSourceParser

        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "main.cpp")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(source)
        config = self._entry_config()
        pr = CppSourceParser(tmp, config).parse_file(src)
        detector = CppEntryPointDetector(config)
        return detector.detect({"main.cpp": pr}, pr.nodes, {})

    @tree_sitter_available
    def test_entry_method_main_not_match(self):
        """A class method named main must NOT be an entry point — C++ requires
        main() to be a free function."""
        entries = self._detect("class A { public: void main() {} };\n")
        cpp_main = [e for e in entries if e.rule_name == "cpp_main"]
        assert cpp_main == [], cpp_main

    @tree_sitter_available
    def test_entry_free_function_main_match(self):
        """A free function main() IS an entry point."""
        entries = self._detect("int main() { return 0; }\n")
        cpp_main = [e for e in entries if e.rule_name == "cpp_main"]
        assert len(cpp_main) >= 1, cpp_main


class TestCppTestFileDetection:
    """C++ test-file detection: exact basenames, suffix/prefix and dir patterns."""

    def test_is_test_file_exact_test_basename(self):
        assert _is_test_file("test.cpp", {}) is True
        assert _is_test_file("latest.cpp", {}) is False

    def test_is_test_file_suffix_match(self):
        assert _is_test_file("foo_test.cpp", {}) is True
        assert _is_test_file("my_test", {}) is False

    def test_is_test_file_prefix_match(self):
        assert _is_test_file("test_main.cpp", {}) is True

    def test_is_test_file_dir_pattern(self):
        assert _is_test_file("tests/foo.cpp", {}) is True
        assert _is_test_file("src/foo.cpp", {}) is False

    @tree_sitter_available
    def test_check_test_file_no_func_requirement(self):
        """File in tests/ without a test-named function is still detected."""
        from graphlint.analyzer.language.cpp.entry import CppEntryPointDetector
        from graphlint.analyzer.language.cpp.parser import CppSourceParser

        source = "int helper() { return 0; }\n"
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "tests", "suite.cpp")
        os.makedirs(os.path.dirname(src), exist_ok=True)
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(source)

        config = {
            "entry_rules": [
                {
                    "name": "cpp_test",
                    "file_pattern": "**/*.cpp",
                    "ast_pattern": "test_file",
                    "enabled": True,
                    "description": "C++ test files",
                },
            ],
        }
        pr = CppSourceParser(tmp, config).parse_file(src)
        detector = CppEntryPointDetector(config)
        entries = detector.detect({"tests/suite.cpp": pr}, pr.nodes, {})
        cpp_test = [e for e in entries if e.rule_name == "cpp_test"]
        assert len(cpp_test) >= 1


@tree_sitter_available
class TestCppIncludesObjects:
    """C++ ``#include`` directives are produced as IncludeInfo objects with resolved local paths."""

    def test_imports_are_include_info_objects(self):
        from graphlint.analyzer.language.cpp.parser import CppSourceParser

        source = '#include <vector>\n#include "Player.h"\n#include "util.h"\n'
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "main.cpp")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(source)

        result = CppSourceParser(tmp, {}).parse_file(src)
        local = [i for i in result.imports]
        assert len(local) >= 2
        assert local[0].include_path == "Player.h"
        assert local[0].is_system is False
        assert local[1].include_path == "util.h"


@tree_sitter_available
class TestCppSpecialMethods:
    """C++ implicitly-invoked special methods (constructors, destructors, operators)."""

    def test_destructor_not_flagged_dead(self):
        from graphlint.analyzer.language.cpp import CppAdapter

        adapter = CppAdapter()
        assert adapter.is_special_name("~Service") is True

        br, wb = self._build({
            "src/main.cpp": (
                "class Service {\n"
                "public:\n"
                "    Service() { }\n"
                "    ~Service() { }\n"
                "    void run() { }\n"
                "};\n"
                "int main() {\n"
                "    Service s;\n"
                "    s.run();\n"
                "    return 0;\n"
                "}\n"
            ),
        })
        nid_map = br.node_id_map
        live = {nid_map[n].qualified_name for n in br.reachable if n in nid_map}
        assert "src.main.Service.~Service" in live, live
        dead_cpp = [
            w for w in wb.get_all()
            if w.warn_type == "dead_code" and "~Service" in str(w.message)
        ]
        assert dead_cpp == [], dead_cpp

    def test_constructor_collision_with_class_name(self):
        _visitor = _parse_source(
            "class Service { public: Service() { } };\n"
        )
        methods = [n for n in _visitor.nodes if n.node_type == "method"]
        assert len(methods) >= 1
        assert methods[0].qualified_name == "test.Service.Service"

    def test_operator_overload_node_created(self):
        _visitor = _parse_source(
            "class Vec { public: bool operator==(const Vec&) const { return true; } };\n"
        )
        names = [n.name for n in _visitor.nodes if n.node_type == "method"]
        assert any(n == "operator==" for n in names), names

    def test_is_special_name_anchored_to_operators(self):
        """operator- and destructor names are special, but a plain free
        function whose name merely starts with ``operator`` (no legal op) is
        NOT."""
        from graphlint.analyzer.language.cpp import CppAdapter

        adapter = CppAdapter()
        assert adapter.is_special_name("~Foo") is True
        assert adapter.is_special_name("operator+") is True
        assert adapter.is_special_name("operator*") is True
        assert adapter.is_special_name("operatorfoo") is False

    def _build(self, files: dict[str, str]) -> Any:
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
        registry = _build_registry()
        adapter = registry.adapter_for_file("x.cpp")
        assert adapter is not None, "C++ adapter not registered"

        prs = {}
        for root, _d, fns in os.walk(tmp):
            for fn in fns:
                if any(fn.endswith(ext) for ext in (".cpp", ".cc", ".cxx",
                                                      ".hpp", ".hh", ".hxx")):
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, tmp).replace(os.sep, "/")
                    prs[rel] = adapter.parse_file(full, tmp, config)

        wb = WarningCollector()
        gb = GraphBuilder(wb, registry=registry, config=config)
        return gb.build(prs), wb


@tree_sitter_available
class TestCppApproachAMemberCall:
    """C++ member-call resolution via the receiver's resolved type (Approach A)."""

    def test_member_call_resolved_via_receiver_type(self):
        source = """\
class Player {
public:
    void update() { }
};
int main() {
    Player player;
    player.update();
    return 0;
}
"""
        visitor = _parse_source(source)
        call_edges = [
            r for r in visitor.references
            if r.edge_type == "call" and "update" in r.target_name
        ]
        assert len(call_edges) >= 1, call_edges
        assert all("Player.update" in r.target_name for r in call_edges), call_edges

    def test_unknown_receiver_falls_back_to_name_based(self):
        source = """\
class Unknown { };
int main() {
    Unknown u;
    u.bogus();
    return 0;
}
"""
        visitor = _parse_source(source)
        refs = visitor.references
        assert all(r.edge_type != "call" or "bogus" not in r.target_name
                   or r.target_name.endswith(".bogus") for r in refs)

    @tree_sitter_available
    def test_field_call_is_arrow(self):
        """p->update() (arrow) resolves the pointee type and emits a call to
        Player.update."""
        source = """\
class Player {
public:
    void update() { }
};
int main() {
    Player* p;
    p->update();
    return 0;
}
"""
        visitor = _parse_source(source)
        call_edges = [
            r for r in visitor.references
            if r.edge_type == "call" and "update" in r.target_name
        ]
        assert len(call_edges) >= 1, call_edges
        assert all("Player.update" in r.target_name for r in call_edges), call_edges

    def test_field_call_dot_fallback(self):
        """obj.update() with an unknown receiver type → conservative edge
        (no fabricated call to a resolved type)."""
        source = """\
class Player {
public:
    void update() { }
};
int foo() {
    obj.update();
    return 0;
}
"""
        visitor = _parse_source(source)
        call_edges = [
            r for r in visitor.references
            if r.edge_type == "call" and "update" in r.target_name
        ]
        for r in call_edges:
            assert not r.target_name.endswith("Player.update"), r


class TestCppApproachAScoping:
    """Approach A receiver-type scoping (B/C/D/E regressions)."""

    def test_anonymous_namespace_members_are_visited(self):
        """Members of an anonymous ``namespace { }`` are real symbols: no
        synthetic qname segment is added, and they are walked for reachability."""
        source = """\
namespace {
class Helper {
public:
    void work() { }
};
Helper helper;
void free_fn() { helper.work(); }
}
int main() {
    free_fn();
    return 0;
}
"""
        visitor = _parse_source(source, module_qname="mod")
        qnames = {n.qualified_name for n in visitor.nodes}
        assert "mod.Helper" in qnames, qnames
        assert "mod.Helper.work" in qnames, qnames
        assert "mod.free_fn" in qnames, qnames
        assert "mod.helper" in qnames, qnames
        # free_fn() is called from main; helper.work() resolves to the
        # anonymous-namespace class's method (not a bare-name edge).
        calls = [r for r in visitor.references if r.edge_type == "call"]
        assert any(r.target_name == "free_fn" for r in calls), calls
        assert any("mod.Helper.work" in r.target_name for r in calls), calls

    def test_templated_class_field_qname_strips_template(self):
        """A templated class's field qname is template_-free (same as its
        type/method qnames)."""
        source = """\
template <typename T>
class Box {
public:
    T value;
    void set(const T& v) { value = v; }
};
"""
        visitor = _parse_source(source, module_qname="mod")
        qnames = {n.qualified_name for n in visitor.nodes}
        assert "mod.Box" in qnames, qnames
        assert "mod.Box.value" in qnames, qnames
        assert "mod.Box.set" in qnames, qnames
        assert all("template_." not in q for q in qnames), qnames

    def test_scoped_var_types_no_cross_method_leak_and_field_shadow(self):
        """Locals must not leak across methods, and a local shadows a class
        field: receiver resolution targets the correct method."""
        source = """\
class Engine { public: void run() { } };
class Car { public: void go() { } };
class Garage {
public:
    Engine e;
    void m1() {
        Car e;
        e.go();
    }
    void m2() {
        e.run();
    }
};
"""
        visitor = _parse_source(source)
        refs = visitor.references
        # m1's local `Car e` shadows the `Engine e` field → Car.go.
        go_calls = [
            r.target_name for r in refs
            if r.edge_type == "call" and "go" in r.target_name
        ]
        assert "test.Car.go" in go_calls, go_calls
        assert all(not t.startswith("test.Engine") for t in go_calls), go_calls
        # m2 reuses the name `e` with no local → the Engine field → Engine.run
        # (a call edge, not a conservative untyped read).
        run_calls = [
            r.target_name for r in refs
            if r.edge_type == "call" and r.target_name.endswith(".run")
        ]
        assert "test.Engine.run" in run_calls, run_calls
        assert all(not t.startswith("test.Car") for t in run_calls), run_calls

    def test_member_call_emits_receiver_read(self):
        """``obj.update()`` reads the receiver variable alongside the member
        edge."""
        source = """\
class Engine {
public:
    void start() { }
};
int main() {
    Engine engine;
    engine.start();
    return 0;
}
"""
        visitor = _parse_source(source)
        refs = visitor.references
        receiver_reads = [
            r for r in refs if r.edge_type == "read" and r.target_name == "engine"
        ]
        assert receiver_reads, [
            (r.edge_type, r.target_name) for r in refs
        ]
        calls = [
            r.target_name for r in refs
            if r.edge_type == "call" and r.target_name.endswith(".start")
        ]
        assert "test.Engine.start" in calls, calls


@tree_sitter_available
class TestCppOutOfClassMethods:
    """Out-of-class member definitions attach to their class as module-qualified methods."""

    def test_out_of_class_method_attached_to_class(self):
        source = """\
class A { public: void f(); };
void A::f() { }
"""
        visitor = _parse_source(source, module_qname="mod")
        methods = [n for n in visitor.nodes if n.node_type == "method"]
        qnames = [m.qualified_name for m in methods]
        assert "mod.A.f" in qnames, qnames
        assert all("::" not in q for q in qnames), qnames

    def test_nested_class_method(self):
        source = """\
class Outer { class Inner { void g(); }; };
void Outer::Inner::g() { }
"""
        visitor = _parse_source(source, module_qname="mod")
        methods = [n for n in visitor.nodes if n.node_type == "method"]
        qnames = [m.qualified_name for m in methods]
        assert "mod.Outer.Inner.g" in qnames, qnames


@tree_sitter_available
class TestCppCrossFileHeader:
    """Cross-file ``.h`` + ``.cpp`` reproduction of the owner's case.

    ``engine/Service.h`` declares ``class Service`` with an in-class
    constructor, destructor and ``run()``; ``main.cpp`` instantiates and calls
    ``run()``. The header must be module-qualified (``engine.Service``), and
    the constructor / destructor must be recognised as implicitly-invoked so
    they are not reported dead across the file boundary.
    """

    def _build(self, files: dict[str, str]) -> Any:
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
        registry = _build_registry()

        # Route each file through the registry so a ``.h`` is sniffed to the
        # C++ adapter consistently with the rest of the graph pipeline.
        prs: dict[str, Any] = {}
        for root, _d, fns in os.walk(tmp):
            for fn in fns:
                if not fn.endswith((".c", ".cpp", ".h", ".cc", ".cxx",
                                    ".hpp", ".hh", ".hxx")):
                    continue
                full = os.path.join(root, fn)
                adapter = registry.adapter_for_file(full)
                if adapter is None:
                    continue
                rel = os.path.relpath(full, tmp).replace(os.sep, "/")
                parsed = adapter.parse_file(full, tmp, config)
                if parsed is not None:
                    prs[rel] = parsed

        wb = WarningCollector()
        gb = GraphBuilder(wb, registry=registry, config=config)
        return gb.build(prs), wb

    def test_service_header_ctor_dtor_not_dead(self):
        """Header ``engine.Service`` + ``main.cpp`` repro: qnames are
        module-qualified, and the constructor/destructor are not dead."""
        br, wb = self._build({
            "engine/Service.h": (
                "class Service {\n"
                "public:\n"
                "    Service() { }\n"
                "    ~Service() { }\n"
                "    void run() { }\n"
                "};\n"
            ),
            "main.cpp": (
                '#include "engine/Service.h"\n'
                "int main() {\n"
                "    Service s;\n"
                "    s.run();\n"
                "    return 0;\n"
                "}\n"
            ),
        })
        nid_map = br.node_id_map
        all_qnames = {
            n.qualified_name for n in nid_map.values()
        }
        # engine/Service.h -> module engine.Service + class Service + methods.
        assert "engine.Service.Service" in all_qnames, all_qnames
        assert "engine.Service.Service.Service" in all_qnames, all_qnames
        assert "engine.Service.Service.~Service" in all_qnames, all_qnames
        assert "main.main" in all_qnames, all_qnames

        live = {nid_map[n].qualified_name for n in br.reachable if n in nid_map}
        # The constructor is recognised as implicitly-invoked (final segment
        # equals its class segment) so it is reachable, not dead. Same for the
        # destructor, which the C++ adapter special-names.
        assert "engine.Service.Service.Service" in live, live
        assert "engine.Service.Service.~Service" in live, live
        # No dead_code warning may target header service members across the
        # file boundary.
        dead_warns = [w for w in wb.get_all() if w.warn_type == "dead_code"]
        for w in dead_warns:
            assert "engine.Service" not in (w.message or ""), w
        # main.cpp resolves the call to Service.run (not left as an unbound
        # name-only edge): some built edge targets the header's run node.  A
        # cross-file member call parses as a read edge to the method, which
        # reachability promotes into the call graph.
        run_node = next(
            n for n in nid_map.values()
            if n.qualified_name == "engine.Service.Service.run"
        )
        run_edges = [
            r for r in br.edges
            if r.target_id == run_node.id and r.edge_type in ("call", "read")
        ]
        assert run_edges, [
            (r.source_id, r.target_id, r.edge_type) for r in br.edges
        ]

    def test_same_name_in_two_headers_no_collision(self):
        """Two headers with the same class name do not collide: qnames stay
        module-qualified per header, and ``::``-qualified uses resolve to the
        correct header's members."""
        br, _wb = self._build({
            "engine/Service.h": (
                "class Service { public: Service() { } void run() { } void stop() { } };\n"
            ),
            "net/Service.h": (
                "class Service { public: Service() { } void run() { } void stop() { } };\n"
            ),
            "main.cpp": (
                '#include "engine/Service.h"\n'
                '#include "net/Service.h"\n'
                "int main() {\n"
                "    engine::Service a;\n"
                "    net::Service b;\n"
                "    a.run();\n"
                "    b.stop();\n"
                "    return 0;\n"
                "    }\n"
            ),
        })
        nid_map = br.node_id_map
        all_qnames = {
            n.qualified_name for n in nid_map.values()
        }
        # Both headers contain a ``class Service`` with the same method names;
        # their module-qualified qnames are distinct, proving same-named
        # classes across headers do not collide.
        assert "engine.Service.Service" in all_qnames, all_qnames
        assert "net.Service.Service" in all_qnames, all_qnames
        assert "engine.Service.Service.run" in all_qnames, all_qnames
        assert "net.Service.Service.run" in all_qnames, all_qnames

        engine_run = nid_map[next(
            nid for nid, n in nid_map.items()
            if n.qualified_name == "engine.Service.Service.run"
        )]
        net_stop = nid_map[next(
            nid for nid, n in nid_map.items()
            if n.qualified_name == "net.Service.Service.stop"
        )]
        engine_cls = nid_map[next(
            nid for nid, n in nid_map.items()
            if n.qualified_name == "engine.Service.Service"
        )]
        net_cls = nid_map[next(
            nid for nid, n in nid_map.items()
            if n.qualified_name == "net.Service.Service"
        )]

        def read_targets(nid: int) -> int:
            return sum(
                1 for r in br.edges
                if r.target_id == nid and r.edge_type in ("call", "read")
            )

        # ``a.run()`` (engine::Service) must reach engine's run member, and
        # ``b.stop()`` (net::Service) net's stop member — resolved against the
        # right qualified nodes, not merged by bare name.
        assert read_targets(engine_run.id) >= 1, [
            (r.source_id, r.target_id, r.edge_type) for r in br.edges
        ]
        assert read_targets(net_stop.id) >= 1, [
            (r.source_id, r.target_id, r.edge_type) for r in br.edges
        ]
        # The ``::``-qualified declarations read the exact header classes.
        assert read_targets(engine_cls.id) >= 1
        assert read_targets(net_cls.id) >= 1

    def test_routing_survives_cwd_change(self):
        """CWD-independent routing: with the working directory moved away from
        the temp project, ``engine/Service.h`` still routes to the C++ adapter
        in the module-qname, adapter-filtering, special-name and public-API
        graph stages."""
        from graphlint.analyzer.graph import GraphBuilder
        from graphlint.analyzer.warnings import WarningCollector
        from graphlint.api import _build_registry
        from graphlint.config.manager import ConfigManager

        files = {
            "engine/Service.h": (
                "class Service {\n"
                "public:\n"
                "    Service() { }\n"
                "    ~Service() { }\n"
                "    void run() { }\n"
                "};\n"
            ),
            "main.cpp": (
                '#include "engine/Service.h"\n'
                "int main() {\n"
                "    Service s;\n"
                "    s.run();\n"
                "    return 0;\n"
                "}\n"
            ),
        }
        tmp = tempfile.mkdtemp()
        for rel, content in files.items():
            full = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(content)

        config = ConfigManager(tmp).load()
        config["_root_dir"] = tmp
        registry = _build_registry()

        prs: dict[str, Any] = {}
        for rel, content in files.items():
            adapter = registry.adapter_for_file(os.path.join(tmp, rel))
            parsed = adapter.parse_file(os.path.join(tmp, rel), tmp, config)
            prs[rel] = parsed

        wb = WarningCollector()
        gb = GraphBuilder(wb, registry=registry, config=config)

        other = tempfile.mkdtemp()
        cwd = os.getcwd()
        try:
            os.chdir(other)
            # Prove the CWD is not below the project root (relative sniffing
            # against CWD alone would fail to find the header).
            assert os.path.relpath(tmp, other).startswith("..")

            # (1) module-qname routing for the header parse key.
            assert gb._module_qname_for("engine/Service.h") == "engine.Service"

            # (2) adapter filter: parse results routed by content sniffing,
            # not by the raw relative key resolved against CWD.
            cpp = registry.adapter_for_file(os.path.join(tmp, "main.cpp"))
            cpp_keys = gb._adapter_parse_results(cpp, prs, registry, tmp)
            assert "engine/Service.h" in cpp_keys, cpp_keys
            c_adapter = registry.adapter_for_file(os.path.join(tmp, "main.c"))
            c_keys = gb._adapter_parse_results(c_adapter, prs, registry, tmp)
            assert "engine/Service.h" not in c_keys, c_keys

            br = gb.build(prs)
        finally:
            os.chdir(cwd)

        nid_map = br.node_id_map
        file_id_to_path = {i: fp for i, fp in enumerate(prs, start=1)}
        dtor = nid_map[next(
            nid for nid, n in nid_map.items()
            if n.qualified_name == "engine.Service.Service.~Service"
        )]
        run = nid_map[next(
            nid for nid, n in nid_map.items()
            if n.qualified_name == "engine.Service.Service.run"
        )]

        # (3) special-name stage: the destructor routes through the C++ adapter
        # (a C-routed file would not special-name ``~Service``).
        assert gb._node_is_special(dtor, file_id_to_path, frozenset())
        # (4) public-API stage runs against the routed adapter.
        assert gb._node_is_public_api(
            run, file_id_to_path, frozenset({"main"})
        ) is False

        # (5) end-to-end: header ctor/dtor stay reachable across the boundary.
        dead = [w for w in wb.get_all() if w.warn_type == "dead_code"]
        for w in dead:
            assert "engine.Service" not in (w.message or ""), w
