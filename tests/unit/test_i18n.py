# -*- coding: utf-8 -*-
"""I18n module tests."""

from unittest.mock import patch

import pytest

from graphlint.i18n import I18nManager
from graphlint.i18n.en import STRINGS as EN_STRINGS
from graphlint.i18n.zh_CN import STRINGS as ZH_STRINGS


@pytest.mark.timeout(30)
class TestI18n:
    """I18n module tests."""

    def teardown_method(self):
        """Reset singleton."""
        I18nManager._instance = None

    def test_en_strings(self):
        """Verify all en.STRINGS values are non-empty strings."""
        for key, val in EN_STRINGS.items():
            assert isinstance(key, str), f"Key {key} should be string"
            assert isinstance(val, str), f"Value {val} should be string"
            assert val, f"Value for key {key} cannot be empty"

    def test_zh_cn_strings(self):
        """Verify all zh_CN.STRINGS values are non-empty strings."""
        for key, val in ZH_STRINGS.items():
            assert isinstance(key, str)
            assert isinstance(val, str)
            assert val, f"Value for key {key} cannot be empty"

    def test_key_parity(self):
        """en.py and zh_CN.py have identical key sets."""
        en_keys = set(EN_STRINGS.keys())
        zh_keys = set(ZH_STRINGS.keys())
        only_in_en = en_keys - zh_keys
        only_in_zh = zh_keys - en_keys
        assert not only_in_en, f"Keys only in en: {only_in_en}"
        assert not only_in_zh, f"Keys only in zh_CN: {only_in_zh}"
        assert en_keys == zh_keys

    def test_i18n_system_lang(self):
        """I18nManager('system') returns Chinese under zh_CN locale."""
        with patch.object(I18nManager, "resolve_lang", return_value="zh_CN"):
            mgr = I18nManager("system")
            assert mgr.t("app.description") == "代码依赖关系图分析工具"
            # Restore singleton
            I18nManager._instance = None

    def test_i18n_force_lang(self):
        """I18nManager('en') returns English."""
        mgr = I18nManager("en")
        assert mgr.t("app.description") == "Code Dependency Graph Analyzer"

    def test_i18n_formatting(self):
        """t('warning.unused_import', count=5) formats string with count."""
        mgr = I18nManager("en")
        result = mgr.t("warning.unused_import", count=5)
        assert "5" in result

    def test_i18n_fallback(self):
        """t('nonexistent.key') returns the key itself."""
        mgr = I18nManager("en")
        result = mgr.t("nonexistent.key")
        assert result == "nonexistent.key"

    def test_i18n_unsupported_lang(self):
        """I18nManager('fr') falls back to English."""
        mgr = I18nManager("fr")
        assert mgr.t("app.description") == "Code Dependency Graph Analyzer"

    def test_i18n_singleton(self):
        """get_instance returns the same instance."""
        I18nManager._instance = None
        inst1 = I18nManager.get_instance("en")
        inst2 = I18nManager.get_instance("en")
        assert inst1 is inst2

    def test_i18n_resolve_lang_system(self):
        """resolve_lang('system') detects via locale."""
        with patch("locale.getlocale", return_value=("zh_CN", "UTF-8")):
            mgr = I18nManager("system")
            lang = mgr.resolve_lang()
            assert lang == "zh_CN"

    def test_i18n_get_all_strings(self):
        """get_all_strings returns current language strings table."""
        mgr = I18nManager("en")
        strings = mgr.get_all_strings()
        assert strings["app.name"] == "graphlint"
        # Verify it returns a copy
        strings["app.name"] = "modified"
        assert mgr.t("app.name") == "graphlint"

    def test_i18n_supported_langs(self):
        """Verify supported languages list."""
        assert I18nManager.SUPPORTED_LANGS == {"en", "zh_CN"}
