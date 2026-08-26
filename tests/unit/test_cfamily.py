# -*- coding: utf-8 -*-
"""Unified C/C++ analyzer — compiler-faithful per-file grammar routing.

The single ``CFamilyAdapter`` owns every C-family extension.  A file's grammar
is decided by its translation unit's language — ``.c`` -> C, ``.cpp/.hpp/...``
-> C++ — and a ``.h`` by the language of the TU(s) that include it, never by
content-sniffing the header.  These tests lock that routing.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from graphlint.analyzer.language.c.constants import _TREE_SITTER_C_AVAILABLE
from graphlint.analyzer.language.cfamily import (
    CFamilyAdapter,
    resolve_header_flavors,
)
from graphlint.analyzer.language.cpp.constants import _TREE_SITTER_CPP_AVAILABLE


def _write(root: str, name: str, content: str) -> str:
    p = os.path.join(root, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(content)
    return p


class TestHeaderFlavorResolver:
    """``.h`` flavor = the language of the TU(s) that include it."""

    def test_mixed_project_routing(self):
        root = tempfile.mkdtemp(prefix="cfam_")
        c_tu = _write(root, "a.c", '#include "util.h"\n#include "types.h"\nint main(void){return 0;}\n')
        cpp_tu = _write(root, "b.cpp", '#include "engine.h"\n#include "types.h"\nint main(){return 0;}\n')
        util = _write(root, "util.h", "int util_fn(void);\n")
        types = _write(root, "types.h", "typedef struct { int a; } Pair;\n")
        engine = _write(root, "engine.h", "class Engine { public: void start(){}; };\n")
        orphan = _write(root, "orphan.h", "int orphan(void);\n")

        flavors = resolve_header_flavors([c_tu, cpp_tu, util, types, engine, orphan])
        assert flavors[util] == "c"        # included only by the C TU
        assert flavors[types] == "c"       # included by both -> shared subset
        assert flavors[engine] == "cpp"    # included only by the C++ TU
        assert flavors[orphan] == "c"      # not included anywhere -> default C


class TestCFamilyAdapter:
    def test_owns_all_c_family_extensions(self):
        adapter = CFamilyAdapter()
        assert adapter.language_name == "c/cpp"
        assert adapter.file_extensions == frozenset({
            ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx",
        })

    def test_grammar_dispatched_by_extension(self):
        root = tempfile.mkdtemp(prefix="cfam_")
        c_src = _write(root, "a.c", "typedef struct { int x; } S;\nint main(void){return 0;}\n")
        cpp_src = _write(root, "b.cpp", "class Engine { public: void start(){}; };\nint main(){return 0;}\n")
        adapter = CFamilyAdapter()
        cfg = {"entry_rules": [], "test_patterns": {}, "_cfamily_header_flavors": {}}

        c_pr = adapter.parse_file(c_src, root, cfg)
        # Parsed as C: no ``class`` node; the C backend's typedef/function model.
        assert not any(n.node_type == "class" for n in c_pr.nodes)
        assert any(n.node_type == "function" for n in c_pr.nodes)

        cpp_pr = adapter.parse_file(cpp_src, root, cfg)
        assert any(n.node_type == "class" for n in cpp_pr.nodes)

    @pytest.mark.skipif(not _TREE_SITTER_CPP_AVAILABLE, reason="no cpp")
    def test_header_grammar_follows_including_tu(self):
        root = tempfile.mkdtemp(prefix="cfam_")
        header = _write(root, "svc.h", "class Service { public: void run(){}; };\n")
        tu = _write(root, "main.cpp", '#include "svc.h"\nint main(){ Service s; s.run(); return 0; }\n')
        flavors = resolve_header_flavors([header, tu])
        adapter = CFamilyAdapter()
        cfg = {"entry_rules": [], "test_patterns": {}, "_cfamily_header_flavors": flavors}

        pr = adapter.parse_file(header, root, cfg)
        assert flavors[header] == "cpp"
        assert any(n.node_type == "class" and n.name == "Service" for n in pr.nodes)

    def test_is_special_name_union(self):
        adapter = CFamilyAdapter()
        assert adapter.is_special_name("~Service") is True      # C++ destructor
        assert adapter.is_special_name("operator+") is True     # C++ operator
        assert adapter.is_special_name("operatorfoo") is False  # not a real operator
        assert adapter.is_special_name("main") is True          # C entry / public
        assert adapter.is_special_name("WinMain") is True       # C entry
        assert adapter.is_special_name("ordinary_fn") is False


class TestCFamilyEndToEnd:
    """A mixed C/C++ project builds into one coherent graph."""

    @pytest.mark.skipif(
        not (_TREE_SITTER_C_AVAILABLE and _TREE_SITTER_CPP_AVAILABLE),
        reason="tree-sitter grammars not installed",
    )
    def test_mixed_project_graph_builds(self):
        from graphlint.analyzer.graph import GraphBuilder
        from graphlint.analyzer.warnings import WarningCollector
        from graphlint.api import _build_registry

        root = tempfile.mkdtemp(prefix="cfam_e2e_")
        _write(root, "lib.h", "typedef struct { int a; } Pair;\nint add(Pair p);\n")
        _write(root, "lib.c", '#include "lib.h"\nint add(Pair p){ return p.a + 1; }\n')
        _write(root, "app.h", "class App { public: int run(); };\n")
        _write(root, "main.cpp", '#include "lib.h"\n#include "app.h"\nint main(){ App a; a.run(); return 0; }\n')

        registry = _build_registry()
        config: dict = {"entry_rules": [], "test_patterns": {}, "_root_dir": root}
        from graphlint.analyzer.language.cfamily import resolve_header_flavors
        config["_cfamily_header_flavors"] = resolve_header_flavors([
            os.path.join(root, f) for f in ("lib.h", "lib.c", "app.h", "main.cpp")
        ])

        prs = {}
        for rootdir, _d, fns in os.walk(root):
            for fn in fns:
                if not fn.endswith((".c", ".cpp", ".h")):
                    continue
                full = os.path.join(rootdir, fn)
                adapter = registry.adapter_for_file(full)
                if adapter is None:
                    continue
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                parsed = adapter.parse_file(full, root, config)
                if parsed is not None:
                    prs[rel] = parsed

        wb = WarningCollector()
        gb = GraphBuilder(wb, registry=registry, config=config)
        br = gb.build(prs)
        # lib.h (included by a C TU) parses as C -> Pair struct exists; app.h
        # (included by a C++ TU) parses as C++ -> App class exists. One registry,
        # one graph.
        qnames = {n.qualified_name for n in br.node_id_map.values()}
        assert any("lib.h" in q or q.startswith("lib.") for q in qnames)
        assert any(q.endswith(".App") or ".App" in q for q in qnames)

    @pytest.mark.skipif(
        not (_TREE_SITTER_C_AVAILABLE and _TREE_SITTER_CPP_AVAILABLE),
        reason="tree-sitter grammars not installed",
    )
    def test_cross_file_member_call_emits_call_edge(self):
        """``Service s; s.run()`` in a TU whose ``Service`` is defined only in
        a header resolves to a type-aware call edge (not a bare name-based
        read edge) — the payoff of the unified analyzer."""
        from graphlint.analyzer.graph import GraphBuilder
        from graphlint.analyzer.warnings import WarningCollector
        from graphlint.api import _build_registry

        root = tempfile.mkdtemp(prefix="cfam_call_")
        _write(
            root, "svc.h",
            "class Service { public: Service(){} ~Service(){} void run(){} };\n",
        )
        _write(
            root, "main.cpp",
            '#include "svc.h"\nint main(){ Service s; s.run(); return 0; }\n',
        )

        registry = _build_registry()
        from graphlint.config.manager import ConfigManager
        config: dict = ConfigManager(root).load()
        config["_root_dir"] = root
        from graphlint.analyzer.language.cfamily import resolve_header_flavors
        config["_cfamily_header_flavors"] = resolve_header_flavors(
            [os.path.join(root, f) for f in ("svc.h", "main.cpp")]
        )

        prs = {}
        for rel in ("svc.h", "main.cpp"):
            full = os.path.join(root, rel)
            adapter = registry.adapter_for_file(full)
            parsed = adapter.parse_file(full, root, config)
            if parsed is not None:
                prs[rel] = parsed

        wb = WarningCollector()
        gb = GraphBuilder(wb, registry=registry, config=config)
        br = gb.build(prs)

        run_id = next(
            (n.id for n in br.node_id_map.values()
             if n.qualified_name.endswith(".Service.run")), 0,
        )
        main_id = next(
            (n.id for n in br.node_id_map.values()
             if n.qualified_name.endswith(".main")), 0,
        )
        assert run_id and main_id, [n.qualified_name for n in br.node_id_map.values()]
        assert any(
            e.source_id == main_id and e.target_id == run_id and e.edge_type == "call"
            for e in br.edges
        ), [(e.source_id, e.target_id, e.edge_type) for e in br.edges]
        # Reachability exercised: main is an entry and the program is reachable,
        # so this test (not just node/edge existence) guards entry/reachability.
        assert br.node_id_map[main_id].is_entry
        assert main_id in br.reachable


@pytest.mark.skipif(
    not (_TREE_SITTER_C_AVAILABLE and _TREE_SITTER_CPP_AVAILABLE),
    reason="tree-sitter grammars not installed",
)
class TestCFamilyProjectMatrix:
    """The maintainer-required matrix: pure-C, pure-C++, and mixed C/C++
    projects all analyse cleanly — no silent corruption, no phantom classes,
    correct per-file grammar."""

    def _build(self, files: dict[str, str]):
        from graphlint.config.manager import ConfigManager
        from graphlint.analyzer.graph import GraphBuilder
        from graphlint.analyzer.warnings import WarningCollector
        from graphlint.api import _build_registry

        root = tempfile.mkdtemp(prefix="cfam_mat_")
        for rel, content in files.items():
            _write(root, rel, content)

        registry = _build_registry()
        # Use the DEFAULT config (with entry rules) so ``main`` is detected as an
        # entry and reachability is actually exercised — not disabled, which would
        # let every program be reported unreachable while the test still passed.
        config = ConfigManager(root).load()
        config["_root_dir"] = root
        config["_cfamily_header_flavors"] = resolve_header_flavors(
            [os.path.join(root, rel) for rel in files]
        )

        prs = {}
        for rel in files:
            full = os.path.join(root, rel)
            adapter = registry.adapter_for_file(full)
            parsed = adapter.parse_file(full, root, config)
            if parsed is not None:
                prs[rel] = parsed

        wb = WarningCollector()
        gb = GraphBuilder(wb, registry=registry, config=config)
        br = gb.build(prs)
        return br, wb, registry

    def test_pure_c_project(self):
        br, wb, _reg = self._build({
            "point.h": (
                "const char* s = \"class Foo\";\n"  # C string literal, must not create a class
                "struct Point { int x; int y; };\n"
                "int add(Point p);\n"
            ),
            "point.c": (
                '#include "point.h"\n'
                "static int impl(int y){ return y + 1; }\n"
                "int add(Point p){ return impl(p.x); }\n"
                "int main(void){ return add((struct Point){0}); }\n"
            ),
        })
        types = {n.node_type for n in br.node_id_map.values()}
        # Pure C: no `class` node, and the "class Foo" string literal does NOT
        # create a phantom class (silent-corruption guard).
        assert "class" not in types, sorted(types)
        assert any(n.node_type == "struct" for n in br.node_id_map.values())
        assert not any(
            n.name == "Foo" for n in br.node_id_map.values()
        ), [n.qualified_name for n in br.node_id_map.values()]

    def test_pure_cpp_project(self):
        br, wb, _reg = self._build({
            "app.hpp": "class App { public: int run(){ return 42; } };\n",
            "main.cpp": '#include "app.hpp"\nint main(){ App a; a.run(); return 0; }\n',
        })
        assert any(n.node_type == "class" and n.name == "App" for n in br.node_id_map.values())
        run = next(
            (n.id for n in br.node_id_map.values()
             if n.qualified_name.endswith(".App.run")), 0,
        )
        main = next(
            (n.id for n in br.node_id_map.values()
             if n.qualified_name.endswith(".main")), 0,
        )
        assert run and main
        assert any(
            e.source_id == main and e.target_id == run and e.edge_type == "call"
            for e in br.edges
        )
        # Reachability is actually exercised: ``main`` is an entry and reachable.
        assert br.node_id_map[main].is_entry, [n.qualified_name for n in br.node_id_map.values()]
        assert main in br.reachable, "main() should be reachable from an entry"

    def test_mixed_project_no_corruption(self):
        """A C header (with a C++-looking string literal) and a C++ header
        coexist: the C header stays C (struct, no phantom class), the C++ header
        becomes a C++ class, and both share one graph."""
        br, wb, _reg = self._build({
            "util.h": (
                'const char* s = "class Foo";\n'
                "struct Point { int x; };\n"
                "int helper(void);\n"
            ),
            "util.c": '#include "util.h"\nint helper(void){ return 1; }\nint main(void){ return helper(); }\n',
            "engine.h": "class Engine { public: void start(){}; };\n",
            "main.cpp": '#include "engine.h"\nint main(){ Engine e; e.start(); return 0; }\n',
        })
        names = {n.qualified_name for n in br.node_id_map.values()}
        # C header parsed as C: struct exists, and the "class Foo" string is not a class.
        assert any(q.endswith(".Point") for q in names), sorted(names)
        assert not any("Foo" in q for q in names), sorted(names)
        # C++ header parsed as C++: a real class.
        assert any(q.endswith(".Engine") for q in names), sorted(names)


@pytest.mark.skipif(
    not (_TREE_SITTER_C_AVAILABLE and _TREE_SITTER_CPP_AVAILABLE),
    reason="tree-sitter grammars not installed",
)
class TestCppResolutionRegressions:
    """Cross-TU member-call resolution regressions the reviewer flagged:
    namespace/template receiver types, constructor call edges, pure-virtual
    declarations, and constructor special names."""

    def _build(self, files: dict[str, str]):
        from graphlint.config.manager import ConfigManager
        from graphlint.analyzer.graph import GraphBuilder
        from graphlint.analyzer.warnings import WarningCollector
        from graphlint.api import _build_registry

        root = tempfile.mkdtemp(prefix="cfam_reg_")
        for rel, content in files.items():
            _write(root, rel, content)

        registry = _build_registry()
        config = ConfigManager(root).load()
        config["_root_dir"] = root
        config["_cfamily_header_flavors"] = resolve_header_flavors(
            [os.path.join(root, rel) for rel in files]
        )

        prs = {}
        for rel in files:
            full = os.path.join(root, rel)
            adapter = registry.adapter_for_file(full)
            parsed = adapter.parse_file(full, root, config)
            if parsed is not None:
                prs[rel] = parsed

        wb = WarningCollector()
        gb = GraphBuilder(wb, registry=registry, config=config)
        br = gb.build(prs)
        file_id_to_path = {i: fp for i, fp in enumerate(prs, start=1)}
        return br, wb, gb, file_id_to_path

    def _calls_to(self, br, source_ids, target):
        target_nodes = {
            n.id for n in br.node_id_map.values() if n.qualified_name.endswith(target)
        }
        return [
            e for e in br.edges
            if e.edge_type == "call"
            and e.source_id in source_ids
            and e.target_id in target_nodes
        ]

    def test_namespace_receiver_call_edge(self):
        br, wb, gb, _ = self._build({
            "geo.h": "namespace geo { class Circle { public: void area(){} }; }\n",
            "main.cpp": '#include "geo.h"\nint main(){ geo::Circle c; c.area(); return 0; }\n',
        })
        main = next((n.id for n in br.node_id_map.values() if n.qualified_name.endswith(".main")), 0)
        assert self._calls_to(br, {main}, "Circle.area"), [
            (e.source_id, e.target_id, e.edge_type) for e in br.edges
        ]

    def test_template_receiver_call_edge(self):
        br, wb, gb, _ = self._build({
            "box.h": "template<typename T> class Box { public: void get(){} }; \n",
            "main.cpp": '#include "box.h"\nint main(){ Box<int> b; b.get(); return 0; }\n',
        })
        main = next((n.id for n in br.node_id_map.values() if n.qualified_name.endswith(".main")), 0)
        assert self._calls_to(br, {main}, "Box.get"), [
            (e.source_id, e.target_id, e.edge_type) for e in br.edges
        ]

    def test_constructor_call_edges(self):
        br, wb, gb, _ = self._build({
            "main.cpp": (
                'class Circle { public: Circle(double){} void area(){} };\n'
                'int main(){ Circle a(1.0); Circle* p = new Circle(2.0); return 0; }\n'
            ),
        })
        main = next((n.id for n in br.node_id_map.values() if n.qualified_name.endswith(".main")), 0)
        calls = self._calls_to(br, {main}, "Circle.Circle")
        assert len(calls) >= 2, [
            (e.source_id, e.target_id, e.edge_type) for e in br.edges
        ]

    def test_pure_virtual_modeled(self):
        br, wb, gb, _ = self._build({
            "shape.h": "class Shape { public: virtual double area() const = 0; };\n",
            "main.cpp": '#include "shape.h"\nint main(){ Shape* s = nullptr; return 0; }\n',
        })
        assert any(
            n.node_type == "method" and n.qualified_name.endswith("Shape.area")
            for n in br.node_id_map.values()
        ), [n.qualified_name for n in br.node_id_map.values()]

    def test_constructor_is_special(self):
        br, wb, gb, file_id_to_path = self._build({
            "main.cpp": (
                'class Service { public: Service(){} void run(){} };\n'
                'int main(){ return 0; }\n'
            ),
        })
        ctor = next(
            (n for n in br.node_id_map.values() if n.qualified_name.endswith(".Service.Service")), None,
        )
        assert ctor is not None
        assert gb._node_is_special(ctor, file_id_to_path, frozenset()) is True
