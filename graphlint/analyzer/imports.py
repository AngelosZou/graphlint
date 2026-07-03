# -*- coding: utf-8 -*-
"""Import statement analysis and unused import detection."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from typing import List, Set, Tuple


@dataclass
class ImportInfo:
    """Import statement information."""

    file_id: int = 0
    line: int = 0
    module_path: str = ""
    imported_names: List[str] = field(default_factory=list)
    import_type: str = "absolute"
    is_used: bool = False
    used_at_lines: List[int] = field(default_factory=list)


class ImportAnalyzer:
    """Import statement analyzer."""

    def __init__(self, root_dir: str = "") -> None:
        """Initialize the import analyzer."""
        self.root_dir: str = os.path.realpath(root_dir) if root_dir else ""

    # ------------------------------------------------------------------
    # Import extraction
    # ------------------------------------------------------------------

    def analyze_import(self, node: ast.Import | ast.ImportFrom) -> List[ImportInfo]:
        """Parse an import AST node into ImportInfo list."""
        results: List[ImportInfo] = []

        if isinstance(node, ast.Import):
            for alias in node.names:
                info = ImportInfo(
                    line=node.lineno,
                    module_path=alias.name,
                    imported_names=[alias.asname or alias.name],
                    import_type="absolute",
                )
                results.append(info)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level or 0

            # Determine import type
            if level > 0:
                import_type = "relative"
            else:
                import_type = self._check_dynamic(module)

            for alias in node.names:
                info = ImportInfo(
                    line=node.lineno,
                    module_path=module,
                    imported_names=[alias.asname or alias.name],
                    import_type=import_type,
                )
                results.append(info)

        return results

    def _check_dynamic(self, module_path: str) -> str:
        """Check if import is dynamic."""
        # Simple literal -> absolute
        return "absolute"

    # ------------------------------------------------------------------
    # Unused import detection
    # ------------------------------------------------------------------

    def detect_unused_imports(
        self,
        imports: List[ImportInfo],
        name_usages: Set[str],
        file_path: str = "",
    ) -> List[Tuple[ImportInfo, str, List[int]]]:
        """Detect unused imports."""
        unused: List[Tuple[ImportInfo, str, List[int]]] = []

        for imp in imports:
            # __future__ imports are language directives
            if imp.module_path == "__future__":
                continue
            # Imports in __init__.py are re-exports
            if self.is_re_export(imp, file_path):
                continue

            # Check if imported names are used
            used_names = [n for n in imp.imported_names if n in name_usages]
            if not used_names:
                names_str = ", ".join(imp.imported_names)
                msg = f"'{names_str}' imported but not used"
                unused.append((imp, msg, []))

        return unused

    # ------------------------------------------------------------------
    # Re-export detection
    # ------------------------------------------------------------------

    @staticmethod
    def is_re_export(imp: ImportInfo, file_path: str) -> bool:
        """Check if import is a re-export in __init__.py."""
        if not file_path:
            return False
        basename = os.path.basename(file_path)
        return basename == "__init__.py"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
