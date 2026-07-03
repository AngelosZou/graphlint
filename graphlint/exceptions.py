# -*- coding: utf-8 -*-
"""Custom exception classes for graphlint."""


class GraphlintError(Exception):
    """Base class for all graphlint exceptions."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message


class ConfigNotFoundError(GraphlintError):
    """Configuration file not found."""

    def __init__(self, path: str = "") -> None:
        msg = f"Config not found: {path}" if path else "Config not found"
        super().__init__(msg)


class InvalidPathError(GraphlintError):
    """Path validation failed."""

    def __init__(self, path: str = "", reason: str = "") -> None:
        msg = f"Invalid path: {path}"
        if reason:
            msg += f" — {reason}"
        super().__init__(msg)


class InvalidParamError(GraphlintError):
    """Invalid parameter value."""

    def __init__(self, param_name: str = "", value: str = "", reason: str = "") -> None:
        if param_name:
            msg = f"Invalid value for parameter {param_name}"
            if value:
                msg += f": {value}"
        else:
            msg = "Invalid parameter value"
        if reason:
            msg += f" — {reason}"
        super().__init__(msg)
