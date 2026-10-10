# -*- coding: utf-8 -*-
"""Configuration manager — reads and writes .graphlint/config.json."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from typing import Any, Optional

from graphlint.config.defaults import DEFAULT_CONFIG
from graphlint.exceptions import ConfigNotFoundError

_TEMPLATE_NOTICE_FILE = ".template_notice.json"


class ConfigManager:
    """Project-level configuration manager."""

    def __init__(self, root_dir: str) -> None:
        """Initialize the configuration manager."""
        self.root_dir: str = os.path.realpath(root_dir)
        self._meta_dir: str = os.path.join(self.root_dir, ".graphlint")
        self.config_path: str = os.path.join(self._meta_dir, "config.json")

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Load the configuration file."""
        config = copy.deepcopy(DEFAULT_CONFIG)
        if os.path.isfile(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as fh:
                    user_config = json.load(fh)
                config = self._deep_merge(config, user_config)
            except (json.JSONDecodeError, OSError):
                pass
        else:
            self._ensure_meta_dir()
            self._write_atomic(self.config_path, DEFAULT_CONFIG)
        return config

    def save(self, config: dict[str, Any]) -> None:
        """Atomically write the configuration file."""
        self._ensure_meta_dir()
        self._write_atomic(self.config_path, config)

    # ------------------------------------------------------------------
    # Key-value access (dot-separated paths)
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any:
        """Get a config value by dot-separated path."""
        config = self.load()
        parts = key.split(".")
        current: Any = config
        for part in parts:
            if isinstance(current, dict):
                if part not in current:
                    raise KeyError(f"Config key not found: {key}")
                current = current[part]
            else:
                raise ValueError(f"Cannot access key '{part}' on non-dict value: {key}")
        return current

    def set(self, key: str, value: Any) -> None:
        """Set a config value by dot-separated path and save."""
        if key == "lang":
            allowed = {"system", "zh_CN", "en"}
            if value not in allowed:
                raise ValueError(f"Invalid language value: {value}, allowed: {allowed}")

        config = self.load()
        parts = key.split(".")
        current: Any = config
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
        self.save(config)

    # ------------------------------------------------------------------
    # Entry rule management
    # ------------------------------------------------------------------

    def add_entry_rule(self, rule: dict[str, Any]) -> None:
        """Add an entry rule."""
        required = {"name", "file_pattern"}
        if not required.issubset(rule.keys()):
            raise ValueError(
                f"Entry rule must contain fields: {', '.join(sorted(required))}"
            )
        rule.setdefault("enabled", True)
        config = self.load()
        config["entry_rules"].append(rule)
        self.save(config)

    def remove_entry_rule(self, rule_name: str) -> None:
        """Remove an entry rule by name."""
        config = self.load()
        rules = config["entry_rules"]
        for i, rule in enumerate(rules):
            if rule.get("name") == rule_name:
                rules.pop(i)
                self.save(config)
                return
        raise ValueError(f"Entry rule not found: {rule_name}")

    # ------------------------------------------------------------------
    # Exclude pattern management
    # ------------------------------------------------------------------

    def add_exclude_pattern(self, pattern: str) -> None:
        """Add a custom exclude pattern."""
        config = self.load()
        config["exclude_patterns"]["user_exclude"].append(pattern)
        self.save(config)

    def remove_exclude_pattern(self, pattern: str) -> None:
        """Remove a custom exclude pattern."""
        config = self.load()
        lst = config["exclude_patterns"]["user_exclude"]
        if pattern not in lst:
            raise ValueError(f"Exclude pattern not found: {pattern}")
        lst.remove(pattern)
        self.save(config)

    # ------------------------------------------------------------------
    # Other operations
    # ------------------------------------------------------------------

    def show(self) -> dict[str, Any]:
        """Return the full current config."""
        return self.load()

    # ------------------------------------------------------------------
    # Default template version (one-time notice + diff)
    # ------------------------------------------------------------------

    def template_version_status(self) -> dict[str, Any]:
        """Compare the template version recorded in config.json with the default.

        ``user`` is None when there is no config file or it records no
        ``version`` key (a hand-written file of unknown vintage, which is
        deliberately not announced).  Never writes anything.
        """
        current = self._default_template_version()
        user_config = self._read_user_config()
        if user_config is None:
            return {
                "config_exists": False,
                "user": None,
                "current": current,
                "outdated": False,
            }
        raw = user_config.get("version")
        try:
            user_version: Optional[int] = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            user_version = None
        return {
            "config_exists": True,
            "user": user_version,
            "current": current,
            "outdated": user_version is not None and user_version < current,
        }

    def pending_template_notice(self) -> Optional[dict[str, int]]:
        """Return a not-yet-shown default-template-update notice, or None.

        A due notice is recorded in the sidecar marker file (never in
        config.json) so it is delivered exactly once per template version.
        """
        status = self.template_version_status()
        if not status["outdated"]:
            return None
        current = int(status["current"])
        if self._notice_shown_version() >= current:
            return None
        self._mark_notice_shown(current)
        return {"user": int(status["user"]), "current": current}

    def diff(self) -> dict[str, Any]:
        """Read-only diff between the shipped default template and config.json.

        Reports the template version gap, every entry rule the user removed,
        added or overrode, and every other top-level key that differs.  The
        user's file is authoritative and is never created or modified, so a
        rule the user deleted deliberately stays deleted.
        """
        current = self._default_template_version()
        user_config = self._read_user_config()
        if user_config is None:
            return {
                "config_exists": False,
                "template_version": {
                    "user": None,
                    "current": current,
                    "outdated": False,
                },
                "entry_rules": {"removed": [], "added": [], "overridden": []},
                "keys": {},
            }

        default_rules = {
            r["name"]: r
            for r in DEFAULT_CONFIG.get("entry_rules", [])
            if isinstance(r, dict) and "name" in r
        }
        user_rules = {
            r["name"]: r
            for r in user_config.get("entry_rules", [])
            if isinstance(r, dict) and "name" in r
        }

        removed = sorted(n for n in default_rules if n not in user_rules)
        added = sorted(n for n in user_rules if n not in default_rules)
        overridden: list[dict[str, Any]] = []
        for name in sorted(n for n in default_rules if n in user_rules):
            fields = self._diff_fields(default_rules[name], user_rules[name])
            if fields:
                overridden.append({"name": name, "fields": fields})

        keys: dict[str, Any] = {}
        for key in sorted(set(DEFAULT_CONFIG) | set(user_config)):
            if key in ("entry_rules", "version"):
                continue
            default_val = DEFAULT_CONFIG.get(key)
            user_val = user_config.get(key)
            if default_val != user_val:
                keys[key] = {"default": default_val, "user": user_val}

        status = self.template_version_status()
        return {
            "config_exists": True,
            "template_version": {
                "user": status["user"],
                "current": current,
                "outdated": status["outdated"],
            },
            "entry_rules": {
                "removed": removed,
                "added": added,
                "overridden": overridden,
            },
            "keys": keys,
        }

    @staticmethod
    def _diff_fields(
        default_rule: dict[str, Any], user_rule: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the per-field differences between two versions of a rule."""
        fields: dict[str, Any] = {}
        for field in sorted(set(default_rule) | set(user_rule)):
            if field == "name":
                continue
            default_val = default_rule.get(field)
            user_val = user_rule.get(field)
            if default_val != user_val:
                fields[field] = {"default": default_val, "user": user_val}
        return fields

    def _default_template_version(self) -> int:
        """The shipped default-template version as an int."""
        try:
            return int(DEFAULT_CONFIG.get("version", 1))
        except (TypeError, ValueError):
            return 1

    def _read_user_config(self) -> Optional[dict[str, Any]]:
        """Read config.json exactly as the user wrote it (defaults NOT merged)."""
        if not os.path.isfile(self.config_path):
            return None
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def _notice_path(self) -> str:
        """Path of the sidecar marker recording the shown notice version."""
        return os.path.join(self._meta_dir, _TEMPLATE_NOTICE_FILE)

    def _notice_shown_version(self) -> int:
        """Template version the user has already been notified about (0 if none)."""
        try:
            with open(self._notice_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return int(data.get("shown_version", 0))
        except (ValueError, TypeError, OSError, AttributeError):
            return 0

    def _mark_notice_shown(self, version: int) -> None:
        """Record that the notice for ``version`` has been delivered."""
        self._ensure_meta_dir()
        self._write_atomic(self._notice_path(), {"shown_version": version})

    def copy_from(self, source_path: str) -> None:
        """Copy config from source path and merge into current directory."""
        real_source = os.path.realpath(source_path)

        # If source is a file, read directly
        if os.path.isfile(real_source):
            src_config_path = real_source
        else:
            # Might be a directory; look for .graphlint/config.json
            candidate = os.path.join(real_source, ".graphlint", "config.json")
            if os.path.isfile(candidate):
                src_config_path = candidate
            else:
                # Recursive search up to 2 levels
                found = self._find_config_in_dir(real_source, max_depth=2)
                if found:
                    src_config_path = found
                else:
                    raise ConfigNotFoundError(f"Config not found in source path: {source_path}")

        with open(src_config_path, "r", encoding="utf-8") as fh:
            source_config = json.load(fh)

        # Merge: overwrite current config, preserve version
        current_version = self.load().get("version", 1)
        source_config["version"] = current_version
        self.save(source_config)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Deep merge two dicts. override values take precedence."""
        result = copy.deepcopy(base)
        for key, val in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(val, dict)
            ):
                result[key] = ConfigManager._deep_merge(result[key], val)
            else:
                result[key] = copy.deepcopy(val)
        return result

    @staticmethod
    def _write_atomic(path: str, data: Any) -> None:
        """Atomically write a JSON file."""
        dir_name = os.path.dirname(path)
        fd, tmp_path = tempfile.mkstemp(suffix=".tmp", prefix="config_", dir=dir_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def _ensure_meta_dir(self) -> None:
        """Ensure the .graphlint/ metadata directory exists."""
        os.makedirs(self._meta_dir, exist_ok=True)

    @staticmethod
    def _find_config_in_dir(directory: str, max_depth: int) -> Optional[str]:
        """Recursively find .graphlint/config.json in a directory."""
        for root, dirs, files in os.walk(directory, followlinks=False):
            depth = root[len(directory) :].count(os.sep)
            if depth > max_depth:
                dirs.clear()  # Prune
                continue
            if ".graphlint" in dirs:
                cfg = os.path.join(root, ".graphlint", "config.json")
                if os.path.isfile(cfg):
                    return cfg
            # Enforce depth limit
            if depth >= max_depth:
                dirs.clear()
        return None