# Contributing to graphlint

Thank you for your interest in contributing! This document outlines the process for contributing to graphlint.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally
3. Create a virtual environment and install dev dependencies:
   ```bash
   python -m venv env
   source env/bin/activate  # or env/Scripts/activate on Windows
   pip install -e ".[dev]"
   ```
4. Create a branch for your changes

## Development Workflow

- Write code that follows [PEP 8](https://peps.python.org/pep-0008/) style
- Add type annotations for all public functions and methods
- Write tests for new functionality
- Ensure all existing tests pass before submitting a PR

## Running Checks

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=graphlint

# Type checking
mypy graphlint/

# Lint
ruff check graphlint/ tests/
```

## Pull Request Process

1. Update the README or documentation if your change affects the public API
2. Add an entry to CHANGELOG.md under the "Unreleased" section
3. Ensure all checks pass (tests, mypy, ruff)
4. Submit your pull request with a clear description of the changes

## Code Style

- Use 4 spaces for indentation (no tabs)
- Maximum line length: 120 characters
- Use `from __future__ import annotations` for modern type hints
- Prefer `Optional[X]` over `X | None` for Python 3.9 compatibility
- Module-level docstrings should briefly describe the module's purpose
- Public functions and classes should have docstrings

## Questions?

Open an issue on [GitHub](https://github.com/AngelosZou/graphlint/issues) if you have questions or need clarification.
