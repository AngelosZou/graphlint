# -*- coding: utf-8 -*-
"""C entry point detector.

Pattern syntax:

    file_match:<glob>           Match file path against glob
    function_def:<pattern>      Match function definitions
    test_file                   Match C test files by filename convention

Entry detection currently uses AST/filename heuristics only;
build-config-driven entry (CMakeLists ``add_executable`` / Makefile link
rules) is a documented follow-up — do NOT implement here.
"""

from __future__ import annotations

from typing import Any

from graphlint.analyzer._types import EntryInfo, NodeInfo, ParseResult
from graphlint.analyzer.language.c.constants import _glob_match, _is_test_file


class CEntryPointDetector:
    """Entry point pattern matcher for C source files.

    Evaluates entry rules against parsed C CST nodes and file-level
    properties to identify C program entry points.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config: dict[str, Any] = config
        rules_source = config.get("entry_rules", [])
        self._rules: list[dict[str, Any]] = [
            r for r in rules_source if r.get("enabled", True)
        ]

    def detect(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        entries: list[EntryInfo] = []

        # Reverse map qualified_name -> node_id, built once before the rule
        # loop to avoid the O(n) scan in _find_node_id. `typedef struct {...}
        # X;` can yield two nodes (struct + typedef) with the same qualified
        # name; when a qname maps to both, prefer the function node id.
        qname_to_id: dict[str, int] = {}
        for n in nodes:
            if n.qualified_name not in qname_to_id:
                qname_to_id[n.qualified_name] = n.id
            elif n.node_type == "function":
                qname_to_id[n.qualified_name] = n.id

        for file_path, pr in parse_results.items():
            if not (file_path.endswith(".c") or file_path.endswith(".h")):
                continue

            for rule in self._rules:
                rule_name = rule.get("name", "")
                if not rule_name:
                    continue
                file_pattern = rule.get("file_pattern", "**/*.c")
                if not _glob_match(file_path, file_pattern):
                    continue

                entries.extend(
                    self._detect_rule(rule, file_path, pr, nodes, qname_to_id)
                )

        return entries

    def _detect_rule(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        qname_to_id: dict[str, int],
    ) -> list[EntryInfo]:
        pattern = rule.get("ast_pattern", "")
        if not pattern:
            return []

        rule_name = rule.get("name", "custom")
        no_propagate = rule.get("no_propagate", False)
        description = rule.get("description", pattern)

        # Whole-pattern handlers (single-token patterns like "test_file")
        if pattern.strip() == "test_file":
            return self._check_test_file(rule, file_path, pr, nodes)

        or_parts = [p.strip() for p in pattern.split(" | ") if p.strip()]
        if not or_parts:
            return []

        # File-level patterns
        for part in or_parts:
            if part.startswith("file_match:"):
                glob_val = part.split(":", 1)[1]
                if _glob_match(file_path, glob_val):
                    return [
                        EntryInfo(
                            rule_name=rule_name,
                            file_path=file_path,
                            line=1,
                            description=description,
                            no_propagate=no_propagate,
                        )
                    ]

        # Node-level patterns
        entries: list[EntryInfo] = []
        for node in pr.nodes:
            for part in or_parts:
                if part.startswith("function_def:"):
                    name_pattern = part.split(":", 1)[1]
                    if node.node_type == "function":
                        if _glob_match(node.name, name_pattern):
                            # Find the real node_id from the global node list
                            nid = self._find_node_id(node.qualified_name, qname_to_id)
                            entries.append(
                                EntryInfo(
                                    rule_name=rule_name,
                                    file_path=file_path,
                                    line=node.line_start,
                                    node_id=nid,
                                    description=description,
                                    no_propagate=no_propagate,
                                )
                            )
                            break

        return entries

    def _check_test_file(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
    ) -> list[EntryInfo]:
        """Detect C test files by filename convention.

        Uses the filename conventions defined in ``constants.py``
        (``_C_TEST_FILE_SUFFIXES`` / ``_C_TEST_FILE_PREFIXES``) plus the
        configured ``test_patterns`` via ``_is_test_file``.

        NOTE: CMake ``enable_testing()`` / ``add_test(NAME ... COMMAND ...)``
        would be the authoritative build-config-driven source for test
        detection; integrating it is scoped as a follow-up, mirroring how C#
        parses ``.csproj``. No behavior change here.
        """
        if not _is_test_file(file_path, self.config):
            return []

        return [
            EntryInfo(
                rule_name=rule.get("name", "c_test"),
                file_path=file_path,
                line=0,
                description=rule.get("description", "C test file"),
                no_propagate=rule.get("no_propagate", True),
            )
        ]

    def _find_node_id(
        self, qualified_name: str, qname_to_id: dict[str, int]
    ) -> int:
        """Look up the global node id for a qualified name (O(1))."""
        return qname_to_id.get(qualified_name, 0)
