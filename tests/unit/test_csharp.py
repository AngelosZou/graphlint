# -*- coding: utf-8 -*-
"""Tests for the C# language adapter."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest

from graphlint.analyzer._types import GraphBuildResult, NodeInfo
from graphlint.analyzer.warnings import WarningCollector
from graphlint.analyzer.language.csharp.constants import (
    _CSHARP_SPECIAL_NAMES,
    _TREE_SITTER_CSHARP_AVAILABLE,
    _file_to_module,
    _is_property_accessor,
    _is_test_file,
)
from graphlint.analyzer.language.csharp.imports import CSharpImportAnalyzer
from graphlint.analyzer.language.csharp.visitor import CSharpVisitor


tree_sitter_available = pytest.mark.skipif(
    not _TREE_SITTER_CSHARP_AVAILABLE, reason="tree-sitter-c-sharp not installed"
)


# =============================================================================
# Constants tests (always runnable)
# =============================================================================


class TestCSharpConstants:
    def test_file_to_module(self):
        assert _file_to_module("Services/AuthService.cs") == "Services.AuthService"
        assert _file_to_module("src/MyApp/Program.cs") == "src.MyApp.Program"
        assert _file_to_module("Models/User.cs") == "Models.User"
        assert _file_to_module("runner.py") == ""

    def test_is_property_accessor(self):
        assert _is_property_accessor("get_Name") is True
        assert _is_property_accessor("set_Name") is True
        assert _is_property_accessor("init_Name") is True
        assert _is_property_accessor("_get_Name") is False
        assert _is_property_accessor("GetName") is False
        assert _is_property_accessor("get_") is False

    def test_special_names(self):
        assert ".ctor" in _CSHARP_SPECIAL_NAMES
        assert "Main" not in _CSHARP_SPECIAL_NAMES  # Main is in public_api_names
        assert "Dispose" in _CSHARP_SPECIAL_NAMES
        assert "ToString" in _CSHARP_SPECIAL_NAMES
        assert "GetEnumerator" in _CSHARP_SPECIAL_NAMES

    def test_is_test_file(self):
        config = {}
        assert _is_test_file("Tests/MyTest.cs", config) is True
        assert _is_test_file("MyServiceTests.cs", config) is True
        assert _is_test_file("test/UnitTest.cs", config) is True
        assert _is_test_file("Services/ProductService.cs", config) is False


# =============================================================================
# Adapter registration tests (always runnable)
# =============================================================================


class TestCSharpAdapterRegistration:
    def test_adapter_imports_gracefully(self):
        """The C# adapter module imports even without tree-sitter-c-sharp."""
        from graphlint.analyzer.language.csharp import CSharpAdapter
        adapter = CSharpAdapter()
        assert adapter.language_name == "csharp"
        assert ".cs" in adapter.file_extensions
        assert adapter.is_special_name(".ctor") is True
        assert adapter.is_special_name("get_Name") is True
        assert adapter.is_special_name("set_Age") is True
        assert adapter.is_special_name("NormalMethod") is False

    def test_registry_skips_csharp_gracefully(self):
        """LanguageRegistry registers the C# adapter only when
        tree-sitter is present."""
        from graphlint.api import _build_registry
        registry = _build_registry()
        # Python adapter is always present; C# depends on tree-sitter-c-sharp
        adapter = registry.adapter_for_file("test.cs")
        if _TREE_SITTER_CSHARP_AVAILABLE:
            assert adapter is not None
        else:
            assert adapter is None
        # When not available, .cs files have no adapter
        # (graphlint skips them with a warning)

    def test_is_special_name_pattern(self):
        """Property accessors match via is_special_name pattern."""
        from graphlint.analyzer.language.csharp import CSharpAdapter
        adapter = CSharpAdapter()
        assert adapter.is_special_name("get_UserName")
        assert adapter.is_special_name("set_UserName")
        assert adapter.is_special_name("init_UserName")
        assert not adapter.is_special_name("RandomMethod")
        # Also matches from the static special_names set
        assert adapter.is_special_name("Dispose")


# =============================================================================
# Visitor tests (require tree-sitter-c-sharp)
# =============================================================================


def _parse_source(source: str) -> CSharpVisitor:
    """Parse *source* into a :class:`CSharpVisitor` (API-compatible with
    both older and newer tree-sitter bindings)."""
    import tree_sitter
    from graphlint.analyzer.language.csharp.constants import _get_csharp_language

    lang = _get_csharp_language()
    parser = tree_sitter.Parser()
    if hasattr(parser, "set_language"):
        parser.set_language(lang)
    else:
        parser.language = lang
    tree = parser.parse(bytes(source, "utf-8"))

    import_analyzer = CSharpImportAnalyzer()
    visitor = CSharpVisitor("TestModule", "test.cs", import_analyzer)
    visitor.visit(tree)
    return visitor


@tree_sitter_available
class TestCSharpVisitorBasic:
    """Basic CST visitor tests — simple C# parsing."""

    @staticmethod
    def _parse(source: str) -> CSharpVisitor:
        return _parse_source(source)

    def test_simple_class_parsing(self):
        source = """\
namespace MyApp;

public class Calculator
{
    public int Add(int a, int b)
    {
        return a + b;
    }
}
"""
        visitor = self._parse(source)
        nodes = visitor.nodes

        class_nodes = [n for n in nodes if n.node_type == "class"]
        assert len(class_nodes) == 1
        assert class_nodes[0].name == "Calculator"
        assert class_nodes[0].qualified_name == "MyApp.Calculator"

        method_nodes = [n for n in nodes if n.node_type == "method"]
        assert len(method_nodes) == 1
        assert method_nodes[0].name == "Add"
        assert method_nodes[0].qualified_name == "MyApp.Calculator.Add"
        assert method_nodes[0].parent_node_id == class_nodes[0].id

    def test_property_parsing(self):
        source = """\
public class User
{
    public string Name { get; set; }
    public int Age { get; set; }
}
"""
        visitor = self._parse(source)
        nodes = visitor.nodes

        prop_nodes = [n for n in nodes if n.node_type == "property"]
        assert len(prop_nodes) == 2
        assert prop_nodes[0].name == "Name"
        assert prop_nodes[1].name == "Age"

    def test_attribute_detection(self):
        source = """\
[ApiController]
[Route("api/[controller]")]
public class ProductsController
{
    [HttpGet]
    public IEnumerable<Product> GetAll() { return null; }
}
"""
        visitor = self._parse(source)
        nodes = visitor.nodes

        class_nodes = [n for n in nodes if n.node_type == "class"]
        assert len(class_nodes) == 1
        assert "ApiController" in class_nodes[0].decorators
        assert "Route" in class_nodes[0].decorators

        method_nodes = [n for n in nodes if n.node_type == "method"]
        assert len(method_nodes) == 1
        assert "HttpGet" in method_nodes[0].decorators

    def test_partial_class_detection(self):
        source = """\
namespace MyApp;

public partial class OrderService
{
    public void Process() { }
}
"""
        visitor = self._parse(source)
        nodes = visitor.nodes

        class_nodes = [n for n in nodes if n.node_type == "class"]
        assert len(class_nodes) == 1
        assert class_nodes[0].is_partial is True
        assert class_nodes[0].canonical_name == "MyApp.OrderService"
        assert "#partial:" in class_nodes[0].qualified_name

    def test_constructor_parsing(self):
        source = """\
public class Service
{
    public Service(string name) { }
}
"""
        visitor = self._parse(source)
        nodes = visitor.nodes

        ctors = [n for n in nodes if n.node_type == "constructor"]
        assert len(ctors) == 1
        assert ctors[0].name == ".ctor"
        assert "Service..ctor" in ctors[0].qualified_name

    def test_interface_parsing(self):
        source = """\
public interface IRepository<T>
{
    T GetById(int id);
    void Save(T entity);
}
"""
        visitor = self._parse(source)
        nodes = visitor.nodes

        iface = [n for n in nodes if n.node_type == "interface"]
        assert len(iface) == 1
        assert iface[0].name == "IRepository"

        methods = [n for n in nodes if n.node_type == "method"]
        assert len(methods) == 2

    def test_inheritance_edge(self):
        source = """\
public class Dog : Animal, IPet
{
    public void Bark() { }
}
"""
        visitor = self._parse(source)
        refs = visitor.references

        inherit_edges = [r for r in refs if r.edge_type == "inherit"]
        assert len(inherit_edges) == 2
        assert any(r.target_name == "Animal" for r in inherit_edges)
        assert any(r.target_name == "IPet" for r in inherit_edges)

    def test_call_edge(self):
        source = """\
public class Runner
{
    public void Execute()
    {
        Helper.DoSomething();
    }
}
"""
        visitor = self._parse(source)
        refs = visitor.references

        call_edges = [r for r in refs if r.edge_type == "call"]
        assert len(call_edges) >= 1
        assert any(r.target_name == "DoSomething" for r in call_edges)


@tree_sitter_available
class TestCSharpVisitorFeatures:
    """Tests for the C# language features added after initial support."""

    def test_enum_member_parsing(self):
        source = """\
namespace MyApp;
public enum Color { Red, Green = 5, Blue }
"""
        visitor = _parse_source(source)
        members = [n for n in visitor.nodes if n.node_type == "enum_member"]
        assert [m.name for m in members] == ["Red", "Green", "Blue"]
        assert all(m.qualified_name.startswith("MyApp.Color.") for m in members)

    def test_pattern_variable(self):
        source = """\
public class C
{
    public void M(object o)
    {
        if (o is Qux q) { q.Run(); }
    }
}
"""
        visitor = _parse_source(source)
        nodes = [n for n in visitor.nodes if n.node_type == "variable" and n.name == "q"]
        assert len(nodes) == 1
        writes = [r for r in visitor.references if r.edge_type == "write" and r.target_name == "q"]
        assert len(writes) == 1
        type_reads = [r for r in visitor.references if r.edge_type == "read" and r.target_name == "Qux"]
        assert len(type_reads) == 1  # no duplicate type reads

    def test_as_and_cast_type_reads(self):
        source = """\
public class C
{
    public void M(object o, object x)
    {
        var a = x as Foo;
        var b = (Bar)o;
    }
}
"""
        visitor = _parse_source(source)
        reads = [r for r in visitor.references if r.edge_type == "read"]
        assert any(r.target_name == "Foo" for r in reads)
        assert any(r.target_name == "Bar" for r in reads)
        # Foo / Bar each read exactly once
        assert len([r for r in reads if r.target_name == "Foo"]) == 1
        assert len([r for r in reads if r.target_name == "Bar"]) == 1

    def test_catch_variable(self):
        source = """\
public class C
{
    public void M()
    {
        try { } catch (TimeoutException ex) { ex.Handle(); }
    }
}
"""
        visitor = _parse_source(source)
        variables = [n for n in visitor.nodes if n.node_type == "variable" and n.name == "ex"]
        assert len(variables) == 1
        writes = [r for r in visitor.references if r.edge_type == "write" and r.target_name == "ex"]
        assert len(writes) == 1
        type_reads = [r for r in visitor.references if r.edge_type == "read" and r.target_name == "TimeoutException"]
        assert len(type_reads) == 1

    def test_foreach_variable(self):
        source = """\
public class C
{
    public void M(System.Collections.Generic.List<Fruit> items)
    {
        foreach (var it in items) { it.Do(); }
        foreach (Fruit f in items) { f.Eat(); }
    }
}
"""
        visitor = _parse_source(source)
        variables = [n for n in visitor.nodes if n.node_type == "variable"]
        assert {v.name for v in variables} == {"it", "f"}
        writes = [r for r in visitor.references if r.edge_type == "write"]
        assert any(r.target_name == "it" for r in writes)
        assert any(r.target_name == "f" for r in writes)
        type_reads = [r for r in visitor.references if r.edge_type == "read" and r.target_name == "Fruit"]
        assert len(type_reads) == 1

    def test_local_function(self):
        source = """\
public class C
{
    public void M()
    {
        void Local() { Helper.Call(); }
        Local();
    }
}
"""
        visitor = _parse_source(source)
        methods = [n for n in visitor.nodes if n.node_type == "method" and n.name == "Local"]
        assert len(methods) == 1
        calls = [r for r in visitor.references if r.edge_type == "call" and r.target_name == "Call"]
        assert len(calls) >= 1

    def test_element_access_read(self):
        source = """\
public class C
{
    public int M(int[] arr)
    {
        return arr[0];
    }
}
"""
        visitor = _parse_source(source)
        reads = [r for r in visitor.references if r.edge_type == "read" and r.target_name == "arr"]
        assert len(reads) == 1

    def test_typeof_read(self):
        source = """\
public class C
{
    public System.Type M()
    {
        return typeof(Widget);
    }
}
"""
        visitor = _parse_source(source)
        reads = [r for r in visitor.references if r.edge_type == "read" and r.target_name == "Widget"]
        assert len(reads) == 1

    def test_explicit_interface_implementation(self):
        source = """\
public class C : IFoo
{
    void IFoo.Bar() { }
    void IFoo.Baz() { }
}
"""
        visitor = _parse_source(source)
        inherits = [r for r in visitor.references if r.edge_type == "inherit" and r.target_name == "IFoo"]
        # base-list (1) + type-level explicit specifier (1, deduped)
        # + method-level (2)
        assert len(inherits) == 4
        method_edges = [r for r in inherits if r.source_qname.endswith(".Bar") or r.source_qname.endswith(".Baz")]
        assert len(method_edges) == 2

    def test_constructor_initializer(self):
        source = """\
public class Base
{
    public Base(string name) { }
}

public class Derived : Base
{
    public Derived() : base("x") { }
    public Derived(int n) : this() { }
}
"""
        visitor = _parse_source(source)
        calls = visitor.references
        base_ctor = [r for r in calls if r.edge_type == "call" and r.target_name == "Base..ctor"]
        this_ctor = [r for r in calls if r.edge_type == "call" and r.target_name.endswith("Derived..ctor") and r.source_qname == "Derived..ctor"]
        assert len(base_ctor) == 1
        assert len(this_ctor) == 1

    def test_local_variables_and_initializer_reads(self):
        source = """\
namespace MyApp;
public class C
{
    public void M()
    {
        var x = arr[0];
        int a = 1, b = 2;
    }
}
"""
        visitor = _parse_source(source)
        variables = [n for n in visitor.nodes if n.node_type == "variable"]
        assert {v.name for v in variables} == {"x", "a", "b"}
        assert all(v.qualified_name.startswith("MyApp.C.M.") for v in variables)
        reads = [r for r in visitor.references if r.edge_type == "read" and r.target_name == "arr"]
        assert len(reads) == 1

    def test_field_declarations_no_infinite_recursion(self):
        source = """\
public class C
{
    private readonly List<OrderItem> _items = new();
    private const int Limit = 10;
    public int Count;
    public string Name { get; set; } = "";

    public void M() { _items.Add(new OrderItem()); }
}
"""
        visitor = _parse_source(source)
        fields = [n for n in visitor.nodes if n.node_type == "field"]
        assert {f.name for f in fields} == {"_items", "Limit", "Count"}
        # Class + property + method must all still be present
        # (walk did not abort)
        types = {n.node_type for n in visitor.nodes}
        assert "class" in types
        assert "property" in types
        assert "method" in types
        # The initializer expression should have been traversed
        assert any(
            r.edge_type == "call" and r.target_name == "OrderItem..ctor"
            for r in visitor.references
        )

    def test_value_local_variable_reads_emitted(self):
        source = """\
public class C
{
    public decimal M()
    {
        decimal value = 0m;
        value += 1m;
        return value;
    }
}
"""
        visitor = _parse_source(source)
        # `value` is a normal local variable here — reads must be emitted so it
        # is not misreported as write-only.
        reads = [r for r in visitor.references if r.edge_type == "read" and r.target_name == "value"]
        assert len(reads) >= 2


class TestCSharpCsproj:
    """Tests for csproj-driven module naming, test detection, and entries."""

    def _make_project(self, csproj_content: str) -> tuple[str, dict]:
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "src", "MyApp", "Services"))
        os.makedirs(os.path.join(tmp, "tests"))
        with open(os.path.join(tmp, "src", "MyApp", "MyApp.csproj"), "w", encoding="utf-8") as fh:
            fh.write(csproj_content)
        open(os.path.join(tmp, "src", "MyApp", "Services", "AuthService.cs"), "w").close()
        open(os.path.join(tmp, "tests", "UnitTest.cs"), "w").close()
        from graphlint.analyzer.language.csharp.constants import _ensure_csproj_cache

        config = {"_root_dir": tmp}
        _ensure_csproj_cache(config)
        return tmp, config

    def test_module_qname_with_root_namespace(self):
        csproj = (
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            "<RootNamespace>MyApp</RootNamespace></PropertyGroup></Project>"
        )
        _, config = self._make_project(csproj)
        from graphlint.analyzer.language.csharp.constants import _module_qname_for_file

        assert _module_qname_for_file("src/MyApp/Services/AuthService.cs", config) == (
            "MyApp.Services.AuthService"
        )

    def test_get_csproj_walk_up(self):
        _, config = self._make_project('<Project Sdk="Microsoft.NET.Sdk"></Project>')
        from graphlint.analyzer.language.csharp.constants import _get_csproj_for_file

        info = _get_csproj_for_file("src/MyApp/Services/AuthService.cs", config)
        assert info is not None
        assert _get_csproj_for_file("src/MyApp/Services/AuthService.cs", {}) is None

    def test_is_test_file_via_csproj(self):
        _, config = self._make_project('<Project Sdk="Microsoft.NET.Sdk"></Project>')
        from graphlint.analyzer.language.csharp.constants import _is_test_file

        # tests/UnitTest.cs has no owning csproj in this fixture —
        # falls back to name matching
        assert _is_test_file("tests/UnitTest.cs", config) is True

    def test_utf16_bom_csproj_is_parsed(self):
        from graphlint.analyzer.language.csharp.constants import _parse_single_csproj

        tmp = tempfile.mkdtemp()
        fp = os.path.join(tmp, "MyApp.csproj")
        content = (
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            "<OutputType>Exe</OutputType>"
            "<RootNamespace>MyApp</RootNamespace>"
            "</PropertyGroup></Project>"
        )
        with open(fp, "wb") as fh:
            fh.write(content.encode("utf-16"))  # UTF-16 LE with BOM (VS style)
        info = _parse_single_csproj(fp)
        assert info is not None
        assert info["output_type"] == "Exe"
        assert info["root_namespace"] == "MyApp"

    def test_is_test_project_false_overrides_sdk_reference(self):
        from graphlint.analyzer.language.csharp.constants import _parse_single_csproj

        tmp = tempfile.mkdtemp()
        fp = os.path.join(tmp, "MyApp.csproj")
        content = (
            '<Project Sdk="Microsoft.NET.Sdk">'
            "<PropertyGroup><IsTestProject>false</IsTestProject></PropertyGroup>"
            '<ItemGroup><PackageReference Include="Microsoft.NET.Test.Sdk" /></ItemGroup>'
            "</Project>"
        )
        with open(fp, "w", encoding="utf-8") as fh:
            fh.write(content)
        info = _parse_single_csproj(fp)
        assert info is not None
        assert info["is_test_project"] is False

    def test_output_type_with_condition_attribute(self):
        from graphlint.analyzer.language.csharp.constants import _parse_single_csproj

        tmp = tempfile.mkdtemp()
        fp = os.path.join(tmp, "MyApp.csproj")
        content = (
            "<Project><PropertyGroup>"
            '<OutputType Condition="\'$(Configuration)\'==\'Release\'">Exe</OutputType>'
            "</PropertyGroup></Project>"
        )
        with open(fp, "w", encoding="utf-8") as fh:
            fh.write(content)
        info = _parse_single_csproj(fp)
        assert info is not None
        assert info["output_type"] == "Exe"

    @tree_sitter_available
    def test_public_items_include_enum_and_interface_members(self):
        from graphlint.analyzer.language.csharp.entry import CSharpEntryPointDetector
        from graphlint.analyzer.language.csharp.parser import CSharpSourceParser

        _, config = self._make_project('<Project Sdk="Microsoft.NET.Sdk"></Project>')
        rel = "src/MyApp/Services/Contracts.cs"
        full = os.path.join(config["_root_dir"], rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(
                "namespace MyApp.Services;\n"
                "public enum Level\n"
                "{\n"
                "    Low,\n"
                "    High\n"
                "}\n"
                "public interface IRepo\n"
                "{\n"
                "    void Save();\n"
                "}\n"
                "public class Impl : IRepo\n"
                "{\n"
                "    public void Save() { }\n"
                "}\n"
            )
        pr = CSharpSourceParser(config["_root_dir"], config).parse_file(full)
        detector = CSharpEntryPointDetector(config)
        entries = detector.detect({rel: pr}, [], {})
        entry_lines = {e.line for e in entries if e.rule_name == "csharp_public_api"}
        # enum (2) + members Low(4)/High(5); interface(7) + member Save(9);
        # class(11) + public method Save(13)
        expected = {2, 4, 5, 7, 9, 11, 13}
        assert expected.issubset(entry_lines), (expected, entry_lines)

    def test_library_default_public_api_entries(self):
        from graphlint.analyzer._types import ParseResult
        from graphlint.analyzer.language.csharp.entry import CSharpEntryPointDetector

        cases = {
            # no OutputType -> SDK default Library
            '<Project Sdk="Microsoft.NET.Sdk"></Project>': 1,
            "<Project><PropertyGroup><OutputType>Library</OutputType></PropertyGroup></Project>": 1,
            "<Project><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup></Project>": 0,
            "<Project><PropertyGroup><OutputType>WinExe</OutputType></PropertyGroup></Project>": 0,
        }
        for csproj, expected in cases.items():
            _, config = self._make_project(csproj)
            pr = ParseResult(file_path="src/MyApp/Services/AuthService.cs")
            pr.nodes = [
                NodeInfo(file_id=0, name="AuthService", qualified_name="AuthService",
                         node_type="class", line_start=1, line_end=1, col_offset=0,
                         parent_node_id=0, visibility="public"),
                NodeInfo(file_id=0, name="Login", qualified_name="AuthService.Login",
                         node_type="method", line_start=2, line_end=2, col_offset=0,
                         parent_node_id=1, visibility="public"),
            ]
            pr.source = "public class AuthService\n{\n    public void Login() { }\n}"
            pr.references = []
            pr.imports = []
            pr.name_usages = set()
            detector = CSharpEntryPointDetector(config)
            entries = detector.detect({"src/MyApp/Services/AuthService.cs": pr}, [], {})
            public_entries = [e for e in entries if e.rule_name == "csharp_public_api"]
            assert len(public_entries) == expected, (csproj, len(public_entries))


    @tree_sitter_available
    def test_public_operator_is_public_api_entry(self):
        """Library-mode public operator overloads are public API entries."""
        from graphlint.analyzer.language.csharp.entry import CSharpEntryPointDetector
        from graphlint.analyzer.language.csharp.parser import CSharpSourceParser

        _, config = self._make_project('<Project Sdk="Microsoft.NET.Sdk"></Project>')
        rel = "src/MyApp/Services/Money.cs"
        full = os.path.join(config["_root_dir"], rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(
                "namespace N;\n"
                "public struct Money\n"
                "{\n"
                "    public static Money operator +(Money a, Money b) => a;\n"
                "}\n"
            )
        pr = CSharpSourceParser(config["_root_dir"], config).parse_file(full)
        detector = CSharpEntryPointDetector(config)
        entries = detector.detect({rel: pr}, [], {})
        entry_lines = {e.line for e in entries if e.rule_name == "csharp_public_api"}
        assert 4 in entry_lines, entry_lines


@tree_sitter_available
class TestCSharpScopeSemantics:
    """Field/variable classification and nested-type parent linkage.

    These used to rely on context-depth heuristics that broke for files
    without namespaces and for nested types; classification now uses an
    explicit method-scope depth.
    """

    def test_local_var_in_namespaceless_file_is_variable(self):
        source = """\
public class Entry
{
    public void Go()
    {
        var c = new Outer();
        int count = 5;
    }
}
"""
        visitor = _parse_source(source)
        local = [n for n in visitor.nodes if n.name in ("c", "count")]
        assert len(local) == 2
        assert all(n.node_type == "variable" for n in local), [
            (n.name, n.node_type) for n in local
        ]
        # parent must be the method, not the class
        entry = next(n for n in visitor.nodes if n.name == "Go")
        assert all(n.parent_node_id == entry.id for n in local)

    def test_field_in_namespaceless_file_is_field(self):
        source = """\
public class Entry
{
    public int counter = 0;
}
"""
        visitor = _parse_source(source)
        field = next(n for n in visitor.nodes if n.name == "counter")
        assert field.node_type == "field"
        cls = next(n for n in visitor.nodes if n.node_type == "class")
        assert field.parent_node_id == cls.id

    def test_nested_type_parent_linked(self):
        source = """\
public class Outer
{
    public class Inner
    {
        public int innerField = 2;
    }
}
"""
        visitor = _parse_source(source)
        outer = next(n for n in visitor.nodes if n.name == "Outer")
        inner = next(n for n in visitor.nodes if n.name == "Inner")
        assert inner.parent_node_id == outer.id
        field = next(n for n in visitor.nodes if n.name == "innerField")
        assert field.node_type == "field"
        assert field.parent_node_id == inner.id

    def test_lambda_body_variable_is_local(self):
        source = """\
public class Entry
{
    public System.Func<int> f = () => { var x = 5; return x; };
}
"""
        visitor = _parse_source(source)
        x = next(n for n in visitor.nodes if n.name == "x")
        assert x.node_type == "variable"


@tree_sitter_available
class TestCSharpPropertyReachability:
    """Property access must make the property reachable
    (C# getter semantics)."""

    def test_property_access_emits_call_edge(self):
        source = """\
public class User
{
    public string Name { get; set; }
    public void Greet() { var s = Name; }
}
"""
        visitor = _parse_source(source)
        # direct property read inside the class — the property node must be
        # referenced (call edge for obj.Prop, read edge for bare Name);
        # either way the property is a *use* and becomes reachable.
        refs = [
            r for r in visitor.references
            if r.target_name == "Name"
        ]
        assert len(refs) >= 1

    def test_var_type_inference_binds_property(self):
        source = """\
public class User
{
    public string Name { get; set; }
}
public class App
{
    public void Run()
    {
        var u = new User();
        var s = u.Name;
    }
}
"""
        visitor = _parse_source(source)
        # the getter invocation must target the property name (not get_Name)
        calls = [
            r for r in visitor.references
            if r.edge_type == "call" and r.target_name == "Name"
        ]
        assert len(calls) >= 1
        # no compiler-mangled get_/set_ targets should be emitted
        mangled = [
            r for r in visitor.references
            if r.target_name.startswith(("get_", "set_", "init_"))
        ]
        assert not mangled

    def test_property_and_enum_reachable_end_to_end(self):
        import tempfile

        from graphlint.analyzer.graph import GraphBuilder
        from graphlint.analyzer.warnings import WarningCollector
        from graphlint.api import _build_registry
        from graphlint.config.manager import ConfigManager

        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "src"))
        src = os.path.join(tmp, "src", "Program.cs")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(
                "namespace MyApp;\n"
                "public enum Level { Low, High }\n"
                "public class User\n"
                "{\n"
                "    public string Name { get; set; }\n"
                "    public int Age { get; set; } = 30;\n"
                "}\n"
                "public class Program\n"
                "{\n"
                "    public static void Main()\n"
                "    {\n"
                "        var u = new User();\n"
                "        u.Name = \"x\";\n"
                "        u.Age = 31;\n"
                "        System.Console.WriteLine(u.Name);\n"
                "        System.Console.WriteLine((int)Level.High);\n"
                "    }\n"
                "}\n"
            )
        config = ConfigManager(tmp).load()
        config["_root_dir"] = tmp
        registry = _build_registry()
        adapter = registry.adapter_for_file("x.cs")
        pr = adapter.parse_file(src, tmp, config)
        wb = WarningCollector()
        gb = GraphBuilder(wb, registry=registry, config=config)
        rel = os.path.relpath(src, tmp).replace(os.sep, "/")
        br = gb.build({rel: pr})
        nid_map = br.node_id_map

        live = {nid_map[n].qualified_name for n in br.reachable if n in nid_map}
        assert "MyApp.User.Name" in live, live
        assert "MyApp.User.Age" in live, live
        assert "MyApp.Level" in live, live
        assert "MyApp.Level.High" in live, live
        assert "MyApp.User" in live, live

        # unused private members are still flagged dead
        assert "MyApp.User.Age" in live  # setter invocation reaches it


@tree_sitter_available
class TestCSharpVisibilitySemantics:
    """Structured visibility drives the public-API surface (library mode)."""

    def _detect_public(self, source: str, csproj: str = "") -> set[int]:
        import tempfile

        from graphlint.analyzer.language.csharp.entry import CSharpEntryPointDetector
        from graphlint.analyzer.language.csharp.parser import CSharpSourceParser

        tmp = tempfile.mkdtemp()
        rel = "Lib.cs"
        full = os.path.join(tmp, rel)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(source)
        if csproj:
            with open(os.path.join(tmp, "Lib.csproj"), "w", encoding="utf-8") as fh:
                fh.write(csproj)
        config = {"_root_dir": tmp}
        pr = CSharpSourceParser(tmp, config).parse_file(full)
        detector = CSharpEntryPointDetector(config)
        entries = detector.detect({rel: pr}, [], {})
        return {
            e.line for e in entries if e.rule_name == "csharp_public_api"
        }

    def test_modifier_order_does_not_hide_public(self):
        lines = self._detect_public(
            "namespace N;\n"
            "static public class OddModifiers\n"
            "{\n"
            "    static public int Helper() => 42;\n"
            "}\n",
            csproj="<Project Sdk=\"Microsoft.NET.Sdk\"></Project>",
        )
        assert 2 in lines, lines   # static public class
        assert 4 in lines, lines   # static public method

    def test_internal_class_members_are_not_public_api(self):
        lines = self._detect_public(
            "namespace N;\n"
            "internal class Hidden\n"
            "{\n"
            "    public int VisibleButInternal() => 1;\n"
            "}\n"
            "public class Exposed\n"
            "{\n"
            "    public int RealApi() => 2;\n"
            "}\n",
            csproj="<Project Sdk=\"Microsoft.NET.Sdk\"></Project>",
        )
        # internal class member must NOT leak into the API surface
        assert 4 not in lines, lines
        # public class public member remains an entry
        assert 8 in lines, lines

    def test_internal_interface_members_are_not_public_api(self):
        lines = self._detect_public(
            "namespace N;\n"
            "internal interface IHidden { void Do(); }\n"
            "public interface IPublic { void Do(); }\n",
            csproj="<Project Sdk=\"Microsoft.NET.Sdk\"></Project>",
        )
        # IHidden member (line 2) must not be an entry
        assert 2 not in lines, lines
        # IPublic member (line 3) is part of the public API
        assert 3 in lines, lines

    def test_nested_in_internal_outer_not_public_api(self):
        lines = self._detect_public(
            "namespace N;\n"
            "internal class Outer\n"
            "{\n"
            "    public class Inner { }\n"
            "}\n",
            csproj="<Project Sdk=\"Microsoft.NET.Sdk\"></Project>",
        )
        assert 4 not in lines, lines


@tree_sitter_available
class TestCSharpEntryPatterns:
    """file_is_program / function_call entry rules behave in OR patterns."""

    def _program_entries(self, source: str, rules: list[dict]) -> list[Any]:
        import tempfile

        from graphlint.analyzer.language.csharp.entry import CSharpEntryPointDetector
        from graphlint.analyzer.language.csharp.parser import CSharpSourceParser

        tmp = tempfile.mkdtemp()
        rel = "Program.cs"
        full = os.path.join(tmp, rel)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(source)
        config = {"_root_dir": tmp, "entry_rules": rules}
        pr = CSharpSourceParser(tmp, config).parse_file(full)
        detector = CSharpEntryPointDetector(config)
        # pass parse-stage nodes so function_call entries can resolve to the
        # containing method's node id
        return detector.detect({rel: pr}, pr.nodes, {})

    def test_top_level_statements_only_calls(self):
        """A file with only top-level calls (no declarations) is a program."""
        entries = self._program_entries(
            "System.Console.WriteLine(\"hi\");\n",
            [{
                "name": "csharp_console_app",
                "file_pattern": "**/Program.cs",
                "ast_pattern": "function_def:Main | file_is_program",
                "enabled": True,
            }],
        )
        assert len(entries) == 1, entries
        assert entries[0].rule_name == "csharp_console_app"

    def test_top_level_statements_with_declaration(self):
        entries = self._program_entries(
            "var x = 10;\nSystem.Console.WriteLine(x);\n",
            [{
                "name": "csharp_console_app",
                "file_pattern": "**/Program.cs",
                "ast_pattern": "function_def:Main | file_is_program",
                "enabled": True,
            }],
        )
        assert len(entries) == 1, entries

    def test_function_call_rule_matches_leaf(self):
        entries = self._program_entries(
            "var builder = WebApplication.CreateBuilder(args);\n"
            "builder.MapGet(\"/\", () => \"ok\");\n"
            "builder.Run();\n",
            [{
                "name": "csharp_minimal_api",
                "file_pattern": "**/*.cs",
                "ast_pattern": "function_call:MapGet",
                "enabled": True,
            }],
        )
        assert len(entries) == 1, entries
        assert entries[0].rule_name == "csharp_minimal_api"

    def test_function_call_rule_matches_dotted_name(self):
        entries = self._program_entries(
            "static class Entry\n"
            "{\n"
            "    static void Main()\n"
            "    {\n"
            "        Application.EnableVisualStyles();\n"
            "        Application.Run(new MainForm());\n"
            "    }\n"
            "}\n",
            [{
                "name": "csharp_winforms",
                "file_pattern": "**/*.cs",
                "ast_pattern": "function_call:Application.Run",
                "enabled": True,
            }],
        )
        assert len(entries) == 1, entries
        assert entries[0].rule_name == "csharp_winforms"
        # the entry should resolve to the containing method (Main),
        # not the file
        assert entries[0].node_id != 0


@tree_sitter_available
class TestCSharpPartialReachability:
    """Partial classes referenced only through interfaces must not be flagged
    as dead code: reachability flows between fragments and the merged node."""

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
        registry = _build_registry()
        adapter = registry.adapter_for_file("x.cs")
        prs = {}
        for root, _d, fns in os.walk(tmp):
            for fn in fns:
                if fn.endswith(".cs"):
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, tmp).replace(os.sep, "/")
                    prs[rel] = adapter.parse_file(full, tmp, config)
        wb = WarningCollector()
        gb = GraphBuilder(wb, registry=registry, config=config)
        return gb.build(prs), wb

    def test_partial_class_via_interface_not_dead(self):
        """Members called through the interface keep the merged node and every
        fragment alive, even though the class name never appears in source."""
        br, wb = self._build({
            "src/Worker.cs": (
                "namespace MyApp;\n"
                "public partial class Worker : IWorker\n"
                "{\n"
                "    public void Process() { }\n"
                "}\n"
            ),
            "src/Worker.Ext.cs": (
                "namespace MyApp;\n"
                "public partial class Worker\n"
                "{\n"
                "    private void Hidden() { }\n"
                "}\n"
            ),
            "src/Program.cs": (
                "namespace MyApp;\n"
                "public interface IWorker { void Process(); }\n"
                "public class Factory\n"
                "{\n"
                "    public static IWorker Create() { return null; }\n"
                "}\n"
                "public class Program\n"
                "{\n"
                "    public static void Main()\n"
                "    {\n"
                "        IWorker w = Factory.Create();\n"
                "        w.Process();\n"
                "    }\n"
                "}\n"
            ),
        })
        nid_map = br.node_id_map
        live = {nid_map[n].qualified_name for n in br.reachable if n in nid_map}
        # merged node + the called member are alive
        assert "MyApp.Worker" in live, live
        assert "MyApp.Worker.Process" in live, live
        # every partial fragment of the live type is alive
        fragments = {
            n.canonical_name
            for n in nid_map.values()
            if n.is_partial and n.canonical_name == "MyApp.Worker"
        }
        assert fragments == {"MyApp.Worker"}
        for n in nid_map.values():
            if n.is_partial and n.canonical_name == "MyApp.Worker":
                assert n.id in br.reachable, (n.qualified_name, "fragment dead")
        # the truly-dead member is still flagged; nothing else is
        dead_warns = [w for w in wb.get_all() if w.warn_type == "dead_code"]
        dead_names = {
            nid_map[w.node_id].qualified_name
            for w in dead_warns
            if w.node_id in nid_map
        }
        assert dead_names == {"MyApp.Worker.Hidden"}, dead_names
        # no mangled fragment names leak into user-facing warnings
        assert not any("#partial:" in qn for qn in dead_names)

    def test_live_class_dead_fragment_member_still_warned(self):
        """A fragment containing only dead members of a LIVE class is not dead
        (the file is load-bearing); only the dead member is reported."""
        br, wb = self._build({
            "src/Part1.cs": (
                "namespace MyApp;\n"
                "public partial class Worker\n"
                "{\n"
                "    public void Process() { System.Console.WriteLine(); }\n"
                "}\n"
            ),
            "src/Part2.cs": (
                "namespace MyApp;\n"
                "public partial class Worker\n"
                "{\n"
                "    private void Helper() { }\n"
                "}\n"
            ),
            "src/Program.cs": (
                "namespace MyApp;\n"
                "public class Program\n"
                "{\n"
                "    public static void Main()\n"
                "    {\n"
                "        var w = new Worker();\n"
                "        w.Process();\n"
                "    }\n"
                "}\n"
            ),
        })
        nid_map = br.node_id_map
        for n in nid_map.values():
            if n.is_partial or (n.qualified_name == "MyApp.Worker"):
                assert n.id in br.reachable, (
                    n.qualified_name, "partial/merged node dead"
                )
        dead_warns = [w for w in wb.get_all() if w.warn_type == "dead_code"]
        dead_names = {
            nid_map[w.node_id].qualified_name
            for w in dead_warns
            if w.node_id in nid_map
        }
        assert dead_names == {"MyApp.Worker.Helper"}, dead_names


@tree_sitter_available
class TestCSharpIndexerAndOperatorReachability:
    """Round-3 fixes: instance indexer access ``obj[i]`` and public operator
    overloads must not be falsely reported dead."""

    def _build(self, files: dict[str, str], csproj_content: str):
        import tempfile

        from graphlint.analyzer.graph import GraphBuilder
        from graphlint.analyzer.warnings import WarningCollector
        from graphlint.api import _build_registry
        from graphlint.config.manager import ConfigManager

        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "App.csproj"), "w", encoding="utf-8") as fh:
            fh.write(csproj_content)
        for rel, content in files.items():
            full = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(content)
        config = ConfigManager(tmp).load()
        config["_root_dir"] = tmp
        registry = _build_registry()
        adapter = registry.adapter_for_file("x.cs")
        prs = {}
        for root, _d, fns in os.walk(tmp):
            for fn in fns:
                if fn.endswith(".cs"):
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, tmp).replace(os.sep, "/")
                    prs[rel] = adapter.parse_file(full, tmp, config)
        wb = WarningCollector()
        gb = GraphBuilder(wb, registry=registry, config=config)
        return gb.build(prs), wb

    def test_instance_indexer_reachable_and_unused_not(self):
        """``a[0]`` keeps A's indexer alive; B's unused indexer stays dead
        (no cross-class over-connect)."""
        br, _wb = self._build({
            "Program.cs": (
                "namespace N;\n"
                "public class A {\n"
                "    private int _x;\n"
                "    public int this[int i] { get { return _x; } set { _x = value; } }\n"
                "}\n"
                "public class B {\n"
                "    private int _x;\n"
                "    public int this[int i] { get { return _x; } set { _x = value; } }\n"
                "}\n"
                "public class Program {\n"
                "    public static void Main() {\n"
                "        var a = new A();\n"
                "        a[0] = 5;\n"
                "        int x = a[0];\n"
                "    }\n"
                "}\n"
            ),
        }, '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup></Project>')
        nid_map = br.node_id_map
        live = {nid_map[n].qualified_name for n in br.reachable if n in nid_map}
        assert "N.A.this[]" in live, sorted(live)
        assert "N.B.this[]" not in live, sorted(live)

    def test_public_operator_reachable_in_library_mode(self):
        """A public operator referenced nowhere internally is still public
        API (library mode): it must not be reported dead."""
        br, _wb = self._build({
            "Lib.cs": (
                "namespace N;\n"
                "public struct Money {\n"
                "    private int _v;\n"
                "    public Money(int v) { _v = v; }\n"
                "    public static Money operator +(Money a, Money b) => new Money(a._v + b._v);\n"
                "}\n"
            ),
        }, '<Project Sdk="Microsoft.NET.Sdk"></Project>')
        nid_map = br.node_id_map
        live = {nid_map[n].qualified_name for n in br.reachable if n in nid_map}
        assert "N.Money.op_Addition" in live, sorted(live)

    def test_unused_public_operator_still_dead_in_exe_mode(self):
        """Negative control: an operator never used and not a library entry
        must still be reported dead."""
        br, _wb = self._build({
            "Program.cs": (
                "namespace N;\n"
                "public class Program {\n"
                "    public static void Main() { }\n"
                "}\n"
                "public struct Money {\n"
                "    private int _v;\n"
                "    public static Money operator +(Money a, Money b) => a;\n"
                "}\n"
            ),
        }, '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup></Project>')
        nid_map = br.node_id_map
        live = {nid_map[n].qualified_name for n in br.reachable if n in nid_map}
        assert "N.Money.op_Addition" not in live, sorted(live)
