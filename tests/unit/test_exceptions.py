# -*- coding: utf-8 -*-
"""Exception class tests."""

import pytest

from graphlint.exceptions import (
    ConfigNotFoundError,
    GraphlintError,
    InvalidParamError,
    InvalidPathError,
)


@pytest.mark.timeout(30)
class TestExceptions:
    """Verify all custom exception classes' behavior."""

    def test_graphlint_error(self):
        """GraphlintError inherits Exception, can be raised and caught."""
        with pytest.raises(GraphlintError):
            raise GraphlintError("Test error")
        try:
            raise GraphlintError("Test message")
        except GraphlintError as e:
            assert str(e) == "Test message"

    def test_config_not_found_error(self):
        """ConfigNotFoundError stores path info."""
        err = ConfigNotFoundError("/path/to/config")
        assert isinstance(err, GraphlintError)
        assert "/path/to/config" in str(err)

    def test_invalid_path_error(self):
        """InvalidPathError stores path and reason."""
        err = InvalidPathError("/bad/path", "path out of bounds")
        assert isinstance(err, GraphlintError)
        assert "/bad/path" in str(err)
        assert hasattr(err, "path") or "/bad/path" in str(err)

    def test_invalid_param_error(self):
        """InvalidParamError stores param name and value."""
        err = InvalidParamError("max_results", "abc", "must be integer")
        assert isinstance(err, GraphlintError)
        assert "max_results" in str(err)

    def test_exception_hierarchy(self):
        """Verify all exceptions are subclasses of GraphlintError."""
        assert issubclass(ConfigNotFoundError, GraphlintError)
        assert issubclass(InvalidPathError, GraphlintError)
        assert issubclass(InvalidParamError, GraphlintError)

    def test_graphlint_error_is_exception(self):
        """Verify GraphlintError is a subclass of Exception."""
        assert issubclass(GraphlintError, Exception)
