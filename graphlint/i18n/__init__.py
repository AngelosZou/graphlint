# -*- coding: utf-8 -*-
"""Internationalization manager — language selection and string translation."""

from __future__ import annotations

import locale
import os
from typing import Any, Dict, Optional


class I18nManager:
    """Internationalized string manager with auto-detection."""

    _instance: Optional["I18nManager"] = None

    SUPPORTED_LANGS: frozenset[str] = frozenset({"zh_CN", "en"})

    def __init__(self, lang_setting: str = "system") -> None:
        """Initialize the i18n manager."""
        self.lang_setting: str = lang_setting
        self._strings: Dict[str, str] = {}
        self._load_language(self.resolve_lang())

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls, lang_setting: str = "system") -> "I18nManager":
        """Get or create the I18nManager singleton."""
        if cls._instance is None:
            cls._instance = cls(lang_setting)
        elif cls._instance.lang_setting != lang_setting:
            cls._instance.lang_setting = lang_setting
            cls._instance._load_language(cls._instance.resolve_lang())
        return cls._instance

    # ------------------------------------------------------------------
    # Language resolution
    # ------------------------------------------------------------------

    def resolve_lang(self) -> str:
        """Resolve the actual language code to use."""
        # Explicit language override
        if self.lang_setting != "system":
            lang = self.lang_setting
            if lang in self.SUPPORTED_LANGS:
                return lang
            return "en"

        # Auto-detection
        detected: Optional[str] = None

        # 1. locale.getdefaultlocale() — returns ISO codes on all platforms
        try:
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                def_loc = locale.getdefaultlocale()
            if def_loc and def_loc[0]:
                detected = def_loc[0]
        except (ValueError, locale.Error):
            pass

        # 2. locale.getlocale() — fallback for platform-specific names
        if detected is None:
            try:
                loc = locale.getlocale()
                if loc and loc[0]:
                    detected = loc[0]
            except (ValueError, locale.Error):
                pass

        # 3. Environment variables
        if detected is None:
            for var in ("LANG", "LC_ALL", "LC_MESSAGES"):
                env_val = os.environ.get(var, "")
                if env_val:
                    detected = env_val
                    break

        # 4. Match known language patterns
        if detected:
            detected_lower = detected.lower().replace("-", "_")
            if detected_lower.startswith("zh") or "chinese" in detected_lower:
                return "zh_CN"

        return "en"

    # ------------------------------------------------------------------
    # String loading
    # ------------------------------------------------------------------

    def _load_language(self, lang_code: str) -> None:
        """Lazy-load string table for the given language."""
        import importlib

        if lang_code == "zh_CN":
            mod = importlib.import_module("graphlint.i18n.zh_CN")
        else:
            mod = importlib.import_module("graphlint.i18n.en")

        self._strings = dict(mod.STRINGS)

    # ------------------------------------------------------------------
    # Translation API
    # ------------------------------------------------------------------

    def t(self, key: str, **kwargs: Any) -> str:
        """Translate a message key."""
        template: Optional[str] = self._strings.get(key)
        if template is None:
            # Fallback: return the key itself
            return key
        if kwargs:
            try:
                return template.format(**kwargs)
            except (KeyError, ValueError):
                return template
        return template

    def get_all_strings(self) -> dict[str, str]:
        """Return the full string table for the current language."""
        return dict(self._strings)
