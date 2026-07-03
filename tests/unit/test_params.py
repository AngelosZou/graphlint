# -*- coding: utf-8 -*-
"""Parameter definition tests."""

import pytest

from graphlint.params import (
    PARAM_DEFS,
    VALID_SORT_BY,
    VALID_WARN_TYPES,
    ParamDef,
    ParamType,
)


@pytest.mark.timeout(30)
class TestParams:
    """Parameter definition validation."""

    def test_all_params_defined(self):
        """Verify PARAM_DEFS has enough entries."""
        assert len(PARAM_DEFS) > 20, f"Expected >20 param defs, got {len(PARAM_DEFS)}"

    def test_param_types_correct(self):
        """Verify each param has a valid ParamType."""
        valid_types = {
            ParamType.STR,
            ParamType.INT,
            ParamType.BOOL,
            ParamType.CHOICE,
            ParamType.FLAG,
        }
        for p in PARAM_DEFS:
            assert p.type in valid_types, f"Param {p.name} invalid type: {p.type}"

    def test_param_categories(self):
        """Verify query/build/config categories all exist."""
        categories = {p.category for p in PARAM_DEFS}
        assert "query" in categories, "Missing query category"
        assert "build" in categories, "Missing build category"
        assert "config" in categories, "Missing config category"

    def test_no_duplicate_names(self):
        """Verify no duplicate names in PARAM_DEFS."""
        names = [p.name for p in PARAM_DEFS]
        duplicates = {n for n in names if names.count(n) > 1}
        assert len(duplicates) == 0, f"Duplicate names: {duplicates}"

    def test_no_duplicate_cli_flags(self):
        """Verify no overlapping CLI flags."""
        all_flags = []
        for p in PARAM_DEFS:
            for flag in p.cli_flags:
                all_flags.append(flag)
        duplicates = {f for f in all_flags if all_flags.count(f) > 1}
        assert len(duplicates) == 0, f"Duplicate CLI flags: {duplicates}"

    def test_valid_warn_types(self):
        """Verify VALID_WARN_TYPES contains all 11 types."""
        expected = {
            "unused_import",
            "dynamic_import",
            "circular_ref",
            "syntax_error",
            "write_only",
            "deprecated_usage",
            "dead_code",
            "type_mismatch",
            "unresolved_ref",
            "unused_variable",
            "file_too_large",
        }
        assert VALID_WARN_TYPES == expected, f"Warn types mismatch: {VALID_WARN_TYPES}"

    def test_valid_sort_by(self):
        """Verify VALID_SORT_BY contains 4 options."""
        expected = {"warnings", "nodes", "edges", "name"}
        assert VALID_SORT_BY == expected, f"Sort options mismatch: {VALID_SORT_BY}"

    def test_each_param_is_paramdef(self):
        """Verify each PARAM_DEFS element is ParamDef instance."""
        for p in PARAM_DEFS:
            assert isinstance(p, ParamDef)

    def test_param_has_help_text(self):
        """Verify each param has help text."""
        for p in PARAM_DEFS:
            assert p.help, f"Param {p.name} missing help text"
            assert isinstance(p.help, str)
