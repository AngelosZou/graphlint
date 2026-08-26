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
