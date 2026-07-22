# -*- coding: utf-8 -*-
"""Multi-language analysis backend framework.

Provides the :class:`LanguageAdapter` ABC and :class:`LanguageRegistry`
for routing source files to the correct language backend.
"""

from graphlint.analyzer.language.base import LanguageAdapter
from graphlint.analyzer.language.registry import LanguageRegistry

__all__ = ["LanguageAdapter", "LanguageRegistry"]
