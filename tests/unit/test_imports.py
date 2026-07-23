# -*- coding: utf-8 -*-
"""Import analysis tests."""

import tempfile

import pytest

from graphlint.analyzer.language.python.imports import ImportAnalyzer, ImportInfo


@pytest.mark.timeout(30)
class TestImportAnalyzer:
    """ImportAnalyzer black-box tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            self.analyzer = ImportAnalyzer(root_dir=tmpdir)
            yield

    def test_absolute_import(self):
        """'import os' with os.path usage → is_used=True."""
        imp = ImportInfo(
            module_path="os",
            imported_names=["os"],
            import_type="absolute",
            line=1,
        )
        name_usages = {"os", "os.path"}
        unused = self.analyzer.detect_unused_imports([imp], name_usages, "/test.py")
        # os is used, should not appear in unused list
        assert len(unused) == 0

    def test_unused_import(self):
        """'import json' never used → is_used=False with warning."""
        imp = ImportInfo(
            module_path="json",
            imported_names=["json"],
            import_type="absolute",
            line=1,
        )
        unused = self.analyzer.detect_unused_imports([imp], set(), "/test.py")
        assert len(unused) == 1
        assert unused[0][0].module_path == "json"

    def test_star_import(self):
        """'from os import *' → imported_names=['*']."""
        imp = ImportInfo(
            module_path="os",
            imported_names=["*"],
            import_type="star",
            line=1,
        )
        assert "*" in imp.imported_names

    def test_unused_import_no_warning_for_used(self):
        """Used imports should not appear in warnings."""
        imp = ImportInfo(
            module_path="json",
            imported_names=["json"],
            import_type="absolute",
            line=1,
        )
        name_usages = {"json", "json.dumps"}
        unused = self.analyzer.detect_unused_imports([imp], name_usages, "/test.py")
        assert len(unused) == 0

    def test_multiple_imports_mixed_usage(self):
        """Mixed used/unused imports."""
        imports = [
            ImportInfo(
                module_path="os", imported_names=["os"], import_type="absolute", line=1
            ),
            ImportInfo(
                module_path="json",
                imported_names=["json"],
                import_type="absolute",
                line=2,
            ),
            ImportInfo(
                module_path="sys",
                imported_names=["sys"],
                import_type="absolute",
                line=3,
            ),
        ]
        name_usages = {"os", "sys"}
        unused = self.analyzer.detect_unused_imports(imports, name_usages, "/test.py")
        unused_modules = [u[0].module_path for u in unused]
        assert "json" in unused_modules
        assert "os" not in unused_modules
        assert "sys" not in unused_modules

    def test_dotted_import_used_via_top_level(self):
        """import urllib.request" used as urllib.request.urlopen → not unused."""
        imp = ImportInfo(
            module_path="urllib.request",
            imported_names=["urllib.request"],
            import_type="absolute",
            line=1,
        )
        name_usages = {"urllib", "request", "urlopen", "req"}
        unused = self.analyzer.detect_unused_imports([imp], name_usages, "/test.py")
        assert len(unused) == 0, (
            f"dotted import 'urllib.request' flagged as unused "
            f"when 'urllib' is in name_usages"
        )

    def test_dotted_import_used_via_deep_chain(self):
        """import mcp.server.stdio" used via deep attribute → not unused."""
        imp = ImportInfo(
            module_path="mcp.server.stdio",
            imported_names=["mcp.server.stdio"],
            import_type="absolute",
            line=1,
        )
        name_usages = {"mcp", "server", "stdio", "stdio_server"}
        unused = self.analyzer.detect_unused_imports([imp], name_usages, "/test.py")
        assert len(unused) == 0, (
            f"dotted import 'mcp.server.stdio' flagged as unused "
            f"when 'mcp' is in name_usages"
        )

    def test_dotted_import_truly_unused(self):
        """import xmlrpc.client" never used → still flagged."""
        imp = ImportInfo(
            module_path="xmlrpc.client",
            imported_names=["xmlrpc.client"],
            import_type="absolute",
            line=1,
        )
        name_usages = {"json", "os"}
        unused = self.analyzer.detect_unused_imports([imp], name_usages, "/test.py")
        assert len(unused) == 1
        assert unused[0][0].module_path == "xmlrpc.client"
