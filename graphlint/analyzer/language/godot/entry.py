# -*- coding: utf-8 -*-
"""Godot entry point detector.

Pattern syntax (same shapes as the other adapters):

    file_match:<glob>           Match the resource path against a glob
    test_file                   Match Godot test files (GUT / gdUnit4 / WAT)
    decorator:<pattern>         Match a file-level annotation (``@tool``) or a
                                declaration annotation (``@rpc``, ``@export``)
    function_def:<pattern>      Match a ``func`` definition
    class_definition:<pattern>  Match a ``class_name`` / inner ``class``

Patterns support OR with `` | ``.

Deliberately *not* here:

* ``main_scene`` / autoloads — they are ordinary ``read`` edges out of the
  ``project.godot`` root node, which the ``godot_project`` rule makes an entry;
  reachability does the rest.
* engine virtuals (``_ready``, ``_process``, …) — ``special_names`` plus the
  core's ``class_special_map`` keep them alive once the script root is live.
* ``class_name`` scripts — they are the project's public API surface and are
  kept alive by a built-in entry (``_detect_public_class``) rather than an
  ``ast_pattern``: the core's ``public_api_names`` is a static set that cannot
  carry project-specific class names.
* literal string dispatch (``call``, ``emit_signal``, ``set`` …) — a built-in
  entry (``_detect_dispatch_targets``) keeps every member whose name appears in
  any file's dispatch literals alive, project-wide.
"""

from __future__ import annotations

import fnmatch
from typing import Any

from graphlint.analyzer._types import EntryInfo, NodeInfo, ParseResult

from .constants import (
    NODE_CLASS,
    NODE_FUNCTION,
    _is_gd_file,
    _is_godot_file,
    _is_test_file,
)
from .imports import config_section

_FILE_LEVEL_PREFIXES = ("file_match:",)
_NODE_PATTERN_PREFIXES = ("function_def:", "decorator:", "class_definition:")


class GdEntryPointDetector:
    """Entry point pattern matcher for Godot scripts and resources."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config: dict[str, Any] = config
        rules_source = config.get("entry_rules", []) if config else []
        self._rules: list[dict[str, Any]] = [
            r for r in rules_source if r.get("enabled", True)
        ]

    # ------------------------------------------------------------------
    # Main detection entry
    # ------------------------------------------------------------------

    def detect(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        entries: list[EntryInfo] = []
        qname_to_global = {n.qualified_name: n.id for n in nodes}

        for file_path, pr in parse_results.items():
            if not _is_godot_file(file_path):
                continue
            for rule in self._rules:
                rule_name = rule.get("name", "")
                if not rule_name:
                    continue
                file_pattern = rule.get("file_pattern", "**/*")
                if not _match_path(file_path, file_pattern):
                    continue
                entries.extend(
                    self._detect_rule(rule, file_path, pr, qname_to_global)
                )
            entries.extend(
                self._detect_public_class(file_path, pr, qname_to_global)
            )

        entries.extend(self._detect_dispatch_targets(parse_results, nodes))

        return entries

    # ------------------------------------------------------------------
    # Built-in string-dispatch keep-alive
    # ------------------------------------------------------------------

    def _detect_dispatch_targets(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
    ) -> list[EntryInfo]:
        """Keep members alive that some script reaches by string.

        ``call("add_score")`` / ``emit_signal("died")`` / ``set("title")`` name a
        method or property by string, and no single file can see which script
        such a call reaches.  Every member named by any literal dispatch name
        found anywhere in the project is therefore treated as an entry: the
        alternative is reporting a method dead that another script calls
        dynamically, which is exactly the false positive this adapter must not
        produce.  Turn it off with ``godot.dispatch_keepalive: false``.
        """
        if not config_section(self.config).get("dispatch_keepalive", True):
            return []

        names: set[str] = set()
        for file_path, pr in parse_results.items():
            if not _is_godot_file(file_path):
                continue
            if _is_gd_file(file_path):
                names |= getattr(pr, "godot_dispatch_names", None) or set()
            # editor-wired ``[connection]`` entries name a method and a signal
            # on a script the scene does not otherwise reference
            for conn in getattr(pr, "godot_connections", None) or ():
                if not isinstance(conn, dict):
                    continue
                for key in ("method", "signal"):
                    value = conn.get(key)
                    if value:
                        names.add(str(value))
        if not names:
            return []

        qname_to_global = {n.qualified_name: n.id for n in nodes}
        entries: list[EntryInfo] = []
        for file_path, pr in parse_results.items():
            if not _is_gd_file(file_path):
                continue
            for node in pr.nodes:
                if node.name not in names:
                    continue
                node_id = qname_to_global.get(node.qualified_name, 0)
                if not node_id:
                    continue
                entries.append(
                    EntryInfo(
                        rule_name="godot_dynamic_dispatch",
                        file_path=file_path,
                        line=node.line_start,
                        node_id=node_id,
                        description=f'literal string dispatch name "{node.name}"',
                        no_propagate=False,
                    )
                )
        return entries

    # ------------------------------------------------------------------
    # Built-in ``class_name`` keep-alive
    # ------------------------------------------------------------------

    def _detect_public_class(
        self,
        file_path: str,
        pr: ParseResult,
        qname_to_global: dict[str, int],
    ) -> list[EntryInfo]:
        """Treat ``class_name`` scripts as public API.

        ``class_name`` registers a type project-wide, so such a script is
        reachable from code graphlint cannot see: another project importing it,
        the editor, or a runtime ``load``.  Making it an entry keeps a library
        script from being reported dead, while its *members* are still analysed
        normally — an uncalled method inside a live ``class_name`` script is
        still dead code.

        Switch this off with ``godot.public_class_api: false`` to get the
        strict orphan-script verdict.
        """
        if not _is_gd_file(file_path):
            return []
        if not config_section(self.config).get("public_class_api", True):
            return []

        class_name = getattr(pr, "godot_class_name", "") or ""
        owner_qname = getattr(pr, "godot_owner_qname", "") or ""
        if not class_name or not owner_qname:
            return []

        node_id = qname_to_global.get(owner_qname, 0)
        if not node_id:
            return []

        line = 1
        for node in pr.nodes:
            if node.qualified_name == owner_qname:
                line = node.line_start
                break

        return [
            EntryInfo(
                rule_name="godot_public_class",
                file_path=file_path,
                line=line,
                node_id=node_id,
                description=f"class_name {class_name} (public API)",
                no_propagate=False,
            )
        ]

    # ------------------------------------------------------------------
    # Rule detection
    # ------------------------------------------------------------------

    def _detect_rule(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        qname_to_global: dict[str, int],
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

        # ---- file-level parts ----
        for part in or_parts:
            if part.startswith("file_match:"):
                glob_val = part.split(":", 1)[1]
                if _match_path(file_path, glob_val):
                    return [
                        EntryInfo(
                            rule_name=rule_name,
                            file_path=file_path,
                            line=1,
                            description=description,
                            no_propagate=no_propagate,
                        )
                    ]
            elif part == "test_file":
                if _is_test_file(file_path, self.config):
                    return [
                        EntryInfo(
                            rule_name=rule_name,
                            file_path=file_path,
                            line=0,
                            description=description,
                            no_propagate=rule.get("no_propagate", True),
                        )
                    ]

        # ---- node-level parts ----
        node_parts = [
            p
            for p in or_parts
            if not p.startswith(_FILE_LEVEL_PREFIXES) and p != "test_file"
        ]
        if not node_parts:
            return []

        pattern_or = " | ".join(node_parts)
        entries: list[EntryInfo] = []
        for node in pr.nodes:
            if not self._check_node_pattern(pattern_or, node, file_path):
                continue
            entries.append(
                EntryInfo(
                    rule_name=rule_name,
                    file_path=file_path,
                    line=node.line_start,
                    node_id=qname_to_global.get(node.qualified_name, 0),
                    description=description,
                    no_propagate=no_propagate,
                )
            )
        return entries

    # ------------------------------------------------------------------
    # Pattern matching on NodeInfo
    # ------------------------------------------------------------------

    def _check_node_pattern(
        self, pattern: str, node: NodeInfo, file_path: str
    ) -> bool:
        parts = pattern.split(" | ")
        if len(parts) > 1:
            return any(
                self._check_node_pattern(p.strip(), node, file_path)
                for p in parts
            )

        if pattern.startswith("function_def:"):
            name_pattern = pattern.split(":", 1)[1]
            if node.node_type in (NODE_FUNCTION, "method"):
                return fnmatch.fnmatch(node.name, name_pattern)

        elif pattern.startswith("decorator:"):
            dec_pattern = pattern.split(":", 1)[1].lstrip("@")
            for decorator in node.decorators:
                if fnmatch.fnmatch(decorator.lstrip("@"), dec_pattern):
                    return True

        elif pattern.startswith("class_definition:"):
            class_pattern = pattern.split(":", 1)[1]
            if node.node_type == NODE_CLASS:
                return fnmatch.fnmatch(node.name, class_pattern)

        return False


def _match_path(file_path: str, pattern: str) -> bool:
    """``fnmatch`` with the ``**/`` root retry the other adapters use."""
    if fnmatch.fnmatch(file_path, pattern):
        return True
    if pattern.startswith("**/"):
        return fnmatch.fnmatch(file_path, pattern[3:])
    return False
