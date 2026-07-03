# -*- coding: utf-8 -*-
"""File hash computation and test file identification."""

from __future__ import annotations

import fnmatch
import hashlib
import os


def compute_file_hash(file_path: str) -> str:
    """Compute the SHA256 hash of a file."""
    sha = hashlib.sha256()
    try:
        with open(file_path, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                sha.update(chunk)
    except OSError:
        return "0000000000000000000000000000000000000000000000000000000000000000"
    return sha.hexdigest()


def is_test_file(file_path: str, test_patterns: dict[str, list[str]]) -> bool:
    """Check if a file is a test file based on naming conventions."""
    basename = os.path.basename(file_path)
    dirname = os.path.dirname(file_path).replace(os.sep, "/")

    # Check file name patterns
    file_patterns = test_patterns.get("file_patterns", ["test_*.py", "*_test.py"])
    for pattern in file_patterns:
        if fnmatch.fnmatch(basename, pattern):
            return True

    # Check directory patterns
    dir_patterns = test_patterns.get("dir_patterns", ["tests/", "test/", "__tests__/"])
    for pattern in dir_patterns:
        # Pattern like "tests/" matches path component
        normalized = pattern.rstrip("/")
        path_parts = dirname.split("/")
        if normalized in path_parts:
            return True
        # Also check if path starts with the directory
        if dirname == normalized or dirname.startswith(normalized + "/"):
            return True

    # Check config file names
    config_files = test_patterns.get("config_files", ["conftest.py"])
    if basename in config_files:
        return True

    return False
