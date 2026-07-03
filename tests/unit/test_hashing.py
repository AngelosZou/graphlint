# -*- coding: utf-8 -*-
"""File hash computation and test file identification tests."""

import hashlib
import os
import tempfile

import pytest

from graphlint.storage.hashing import compute_file_hash, is_test_file


@pytest.mark.timeout(30)
class TestComputeFileHash:
    """compute_file_hash tests."""

    def test_compute_file_hash(self):
        """Create temp file with known content, verify SHA256 hash matches."""
        content = b"hello world"
        expected_hash = hashlib.sha256(content).hexdigest()

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            tmp_path = f.name

        try:
            result = compute_file_hash(tmp_path)
            assert result == expected_hash
        finally:
            os.unlink(tmp_path)

    def test_compute_file_hash_large(self):
        """Create 5MB zero-filled file, verify hash computation."""
        size = 5 * 1024 * 1024  # 5MB

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"\x00" * size)
            tmp_path = f.name

        try:
            result = compute_file_hash(tmp_path)
            # Pre-compute SHA256 of 5MB zeros
            expected = hashlib.sha256(b"\x00" * size).hexdigest()
            assert result == expected
        finally:
            os.unlink(tmp_path)

    def test_compute_file_hash_empty(self):
        """Empty file returns SHA256 of empty string."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            tmp_path = f.name

        try:
            result = compute_file_hash(tmp_path)
            expected = hashlib.sha256(b"").hexdigest()
            assert result == expected
        finally:
            os.unlink(tmp_path)

    def test_compute_file_hash_not_found(self):
        """Non-existent file returns zero hash."""
        result = compute_file_hash("/nonexistent/path/file.py")
        assert (
            result == "0000000000000000000000000000000000000000000000000000000000000000"
        )


@pytest.mark.timeout(30)
class TestIsTestFile:
    """is_test_file tests."""

    def test_is_test_file_by_name(self):
        """File named test_foo.py returns True."""
        patterns = {
            "file_patterns": ["test_*.py", "*_test.py"],
            "dir_patterns": [],
            "config_files": [],
        }
        assert is_test_file("test_foo.py", patterns) is True
        assert is_test_file("foo.py", patterns) is False

    def test_is_test_file_by_dir(self):
        """File under tests/ directory returns True."""
        patterns = {
            "file_patterns": [],
            "dir_patterns": ["tests/", "test/", "__tests__/"],
            "config_files": [],
        }
        assert is_test_file("project/tests/foo.py", patterns) is True
        assert is_test_file("project/test/bar.py", patterns) is True
        assert is_test_file("project/__tests__/baz.py", patterns) is True

    def test_is_test_file_conftest(self):
        """conftest.py returns True."""
        patterns = {
            "file_patterns": [],
            "dir_patterns": [],
            "config_files": ["conftest.py"],
        }
        assert is_test_file("conftest.py", patterns) is True
        assert is_test_file("subdir/conftest.py", patterns) is True

    def test_is_test_file_negative(self):
        """prod.py returns False."""
        patterns = {
            "file_patterns": ["test_*.py", "*_test.py"],
            "dir_patterns": ["tests/"],
            "config_files": ["conftest.py"],
        }
        assert is_test_file("prod.py", patterns) is False
        assert is_test_file("src/util.py", patterns) is False

    def test_is_test_file_suffix_match(self):
        """*_test.py pattern matches foo_test.py."""
        patterns = {
            "file_patterns": ["test_*.py", "*_test.py"],
            "dir_patterns": [],
            "config_files": [],
        }
        assert is_test_file("foo_test.py", patterns) is True
        assert is_test_file("foo_test_utils.py", patterns) is False

    def test_is_test_file_default_patterns(self):
        """Full validation with default test_patterns dict."""
        patterns = {
            "file_patterns": ["test_*.py", "*_test.py"],
            "dir_patterns": ["tests/", "test/", "__tests__/"],
            "config_files": ["conftest.py"],
        }
        assert is_test_file("test_example.py", patterns) is True
        assert is_test_file("src/tests/example.py", patterns) is True
        assert is_test_file("src/test/example.py", patterns) is True
        assert is_test_file("src/__tests__/example.py", patterns) is True
        assert is_test_file("conftest.py", patterns) is True
        assert is_test_file("src/main.py", patterns) is False
