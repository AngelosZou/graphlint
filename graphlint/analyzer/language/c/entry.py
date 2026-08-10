# -*- coding: utf-8 -*-
"""C entry point detector.

Pattern syntax:

    file_match:<glob>           Match file path against glob
    function_def:<pattern>      Match function definitions
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any

from graphlint.analyzer._types import EntryInfo, NodeInfo, ParseResult


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

        for file_path, pr in parse_results.items():
            if not (file_path.endswith(".c") or file_path.endswith(".h")):
                continue

            for rule in self._rules:
                rule_name = rule.get("name", "")
                if not rule_name:
                    continue
                file_pattern = rule.get("file_pattern", "**/*.c")
                matched = fnmatch.fnmatch(file_path, file_pattern)
                if not matched and file_pattern.startswith("**/"):
                    matched = fnmatch.fnmatch(file_path, file_pattern[3:])
                if not matched:
                    continue

                entries.extend(
                    self._detect_rule(rule, file_path, pr, nodes, node_id_map)
                )

        return entries

    def _detect_rule(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        pattern = rule.get("ast_pattern", "")
        if not pattern:
            return []

        rule_name = rule.get("name", "custom")
        no_propagate = rule.get("no_propagate", False)
        description = rule.get("description", pattern)

        or_parts = [p.strip() for p in pattern.split(" | ") if p.strip()]
        if not or_parts:
            return []

        # File-level patterns
        for part in or_parts:
            if part.startswith("file_match:"):
                glob_val = part.split(":", 1)[1]
                if fnmatch.fnmatch(file_path, glob_val):
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
                        if fnmatch.fnmatch(node.name, name_pattern):
                            # Find the real node_id from the global node list
                            nid = self._find_node_id(node.qualified_name, nodes)
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

    def _find_node_id(
        self, qualified_name: str, nodes: list[NodeInfo]
    ) -> int:
        """Find the global node id for a given qualified name."""
        for n in nodes:
            if n.qualified_name == qualified_name:
                return n.id
        return 0
