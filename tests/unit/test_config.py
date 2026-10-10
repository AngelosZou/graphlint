# -*- coding: utf-8 -*-
"""ConfigManager unit tests."""

import json
import os
import tempfile

import pytest

from graphlint.config.defaults import DEFAULT_CONFIG
from graphlint.config.manager import ConfigManager


@pytest.mark.timeout(30)
class TestConfigManager:
    """ConfigManager black-box test suite."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Each test uses a separate temp dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            self.cm = ConfigManager(tmpdir)
            yield

    # ── Tests ─────────────────────────────────────────────────

    def test_config_save_and_load(self):
        """Save config to .graphlint/config.json, reload, verify all fields match defaults."""
        # First load writes default config
        config1 = self.cm.load()
        # Verify config.json was created
        config_path = self.cm.config_path
        assert os.path.isfile(config_path), "config.json should be auto-created"

        # Verify content (deep check key fields)
        assert config1["version"] == DEFAULT_CONFIG["version"]
        assert config1["lang"] == DEFAULT_CONFIG["lang"]
        assert config1["output"] == DEFAULT_CONFIG["output"]
        assert config1["performance"] == DEFAULT_CONFIG["performance"]
        assert config1["exclude_patterns"] == DEFAULT_CONFIG["exclude_patterns"]
        assert len(config1["entry_rules"]) == len(DEFAULT_CONFIG["entry_rules"])

        # Modify and save
        config1["lang"] = "en"
        self.cm.save(config1)

        # Reload, verify persistence
        config2 = self.cm.load()
        assert config2["lang"] == "en"
        assert config2["version"] == DEFAULT_CONFIG["version"]
        # Other fields still intact
        assert config2["output"] == DEFAULT_CONFIG["output"]

    def test_config_set_get(self):
        """Set a value, get it back, verify correctness."""
        self.cm.set("lang", "zh_CN")
        val = self.cm.get("lang")
        assert val == "zh_CN"

        # Nested path
        self.cm.set("output.default_max_results", 100)
        assert self.cm.get("output.default_max_results") == 100

        # Get non-existent key
        with pytest.raises(KeyError):
            self.cm.get("nonexistent_key")

    def test_config_set_invalid_lang(self):
        """Setting lang to 'invalid' raises ValueError."""
        with pytest.raises(ValueError, match="Invalid language value"):
            self.cm.set("lang", "invalid")

    def test_config_add_remove_entry_rule(self):
        """Add entry rule, verify in list, remove by name, verify removed."""
        rule = {
            "name": "custom_rule",
            "file_pattern": "**/*.py",
            "ast_pattern": "custom_check",
            "description": "Custom rule",
        }
        self.cm.add_entry_rule(rule)
        config = self.cm.load()
        names = [r["name"] for r in config["entry_rules"]]
        assert "custom_rule" in names

        # Remove
        self.cm.remove_entry_rule("custom_rule")
        config = self.cm.load()
        names = [r["name"] for r in config["entry_rules"]]
        assert "custom_rule" not in names

    def test_config_remove_entry_rule_not_found(self):
        """Removing non-existent rule raises ValueError."""
        with pytest.raises(ValueError, match="Entry rule not found"):
            self.cm.remove_entry_rule("nonexistent_rule")

    def test_config_add_entry_rule_missing_fields(self):
        """Adding incomplete rule raises ValueError."""
        with pytest.raises(ValueError, match="Entry rule must contain fields"):
            self.cm.add_entry_rule({"name": "incomplete"})

    def test_config_add_remove_exclude(self):
        """Add exclude pattern to user_exclude, remove, verify."""
        self.cm.add_exclude_pattern("temp/")
        config = self.cm.load()
        assert "temp/" in config["exclude_patterns"]["user_exclude"]

        self.cm.remove_exclude_pattern("temp/")
        config = self.cm.load()
        assert "temp/" not in config["exclude_patterns"]["user_exclude"]

    def test_config_remove_exclude_not_found(self):
        """Removing non-existent exclude pattern raises ValueError."""
        with pytest.raises(ValueError, match="Exclude pattern not found"):
            self.cm.remove_exclude_pattern("nonexistent/")

    def test_config_atomic_write(self):
        """Verify save uses temp file + os.replace (.tmp files should not remain)."""
        config_path = self.cm.config_path
        meta_dir = os.path.dirname(config_path)

        # Execute save
        self.cm.save(DEFAULT_CONFIG)

        # Verify config.json exists
        assert os.path.isfile(config_path)

        # Verify no .tmp files in meta_dir
        if os.path.isdir(meta_dir):
            tmp_files = [f for f in os.listdir(meta_dir) if f.endswith(".tmp")]
            assert len(tmp_files) == 0, f"Residual .tmp files: {tmp_files}"

    def test_config_merge_defaults(self):
        """Corrupt config.json missing some keys, verify defaults fill in."""
        # Create .graphlint/config.json with partial config
        os.makedirs(os.path.join(self.tmpdir, ".graphlint"), exist_ok=True)
        partial_config = {"lang": "en"}  # Only lang, others missing
        with open(self.cm.config_path, "w", encoding="utf-8") as f:
            json.dump(partial_config, f)

        # Load should deep-merge with defaults
        config = self.cm.load()
        assert config["lang"] == "en"  # Overridden value kept
        assert config["version"] == DEFAULT_CONFIG["version"]  # From defaults
        assert "entry_rules" in config  # From defaults
        assert len(config["entry_rules"]) == len(DEFAULT_CONFIG["entry_rules"])
        assert config["output"] == DEFAULT_CONFIG["output"]
        assert config["performance"] == DEFAULT_CONFIG["performance"]

    def test_config_corrupt_json(self):
        """Corrupt JSON file falls back to default config."""
        os.makedirs(os.path.join(self.tmpdir, ".graphlint"), exist_ok=True)
        with open(self.cm.config_path, "w", encoding="utf-8") as f:
            f.write("{invalid json!!!!}")

        config = self.cm.load()
        assert config == DEFAULT_CONFIG

    def test_config_show(self):
        """show returns deep copy of full config."""
        config = self.cm.show()
        assert config == DEFAULT_CONFIG
        # Verify it's a deep copy
        config["lang"] = "en"
        # Second show should be unaffected
        config2 = self.cm.show()
        assert config2["lang"] == "system"

    def test_config_get_path_not_found(self):
        """Accessing non-existent dot-notation path raises KeyError."""
        with pytest.raises(KeyError):
            self.cm.get("output.nonexistent")

    def test_config_set_nested_path(self):
        """Set value at nested path."""
        self.cm.set("performance.max_file_size_mb", 20)
        assert self.cm.get("performance.max_file_size_mb") == 20


@pytest.mark.timeout(30)
class TestConfigTemplateNoticeAndDiff:
    """Default-template version: one-time notice + read-only `config diff`."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Each test uses a separate temp dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            self.cm = ConfigManager(tmpdir)
            yield

    # ── Helpers ───────────────────────────────────────────────

    def _write_config(self, config: dict) -> None:
        os.makedirs(os.path.dirname(self.cm.config_path), exist_ok=True)
        with open(self.cm.config_path, "w", encoding="utf-8") as fh:
            json.dump(config, fh)

    def _config_from_previous_template(self) -> dict:
        """A config.json as an older graphlint would have written it."""
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        cfg["version"] = 1
        return cfg

    def _read_config_bytes(self) -> bytes:
        with open(self.cm.config_path, "rb") as fh:
            return fh.read()

    def _notice_marker_path(self) -> str:
        return os.path.join(self.tmpdir, ".graphlint", ".template_notice.json")

    # ── diff ──────────────────────────────────────────────────

    def test_diff_without_config_file_creates_nothing(self):
        """diff never creates .graphlint/config.json."""
        result = self.cm.diff()
        assert result["config_exists"] is False
        assert result["entry_rules"] == {"removed": [], "added": [], "overridden": []}
        assert result["keys"] == {}
        assert not os.path.isfile(self.cm.config_path)

    def test_diff_reports_removed_default_rule(self):
        """A default rule the user deleted is reported as removed, not restored."""
        cfg = self._config_from_previous_template()
        cfg["entry_rules"] = [
            r for r in cfg["entry_rules"] if r["name"] != "flask_app"
        ]
        self._write_config(cfg)
        before = self._read_config_bytes()

        diff = self.cm.diff()

        assert diff["entry_rules"]["removed"] == ["flask_app"]
        assert diff["entry_rules"]["added"] == []
        assert diff["entry_rules"]["overridden"] == []
        assert diff["template_version"]["outdated"] is True
        assert self._read_config_bytes() == before  # read-only

    def test_diff_reports_added_rule(self):
        """A user rule absent from the defaults is reported as added."""
        cfg = self._config_from_previous_template()
        cfg["entry_rules"].append(
            {
                "name": "my_entry",
                "file_pattern": "**/*.py",
                "ast_pattern": "function_def:main",
            }
        )
        self._write_config(cfg)

        diff = self.cm.diff()

        assert diff["entry_rules"]["added"] == ["my_entry"]
        assert diff["entry_rules"]["removed"] == []
        assert diff["entry_rules"]["overridden"] == []

    def test_diff_reports_overridden_rule_field(self):
        """A changed field on a default rule is reported with both values."""
        default_pattern = next(
            r["ast_pattern"]
            for r in DEFAULT_CONFIG["entry_rules"]
            if r["name"] == "flask_app"
        )
        cfg = self._config_from_previous_template()
        for rule in cfg["entry_rules"]:
            if rule["name"] == "flask_app":
                rule["ast_pattern"] = "function_call:*.run"
        self._write_config(cfg)

        diff = self.cm.diff()

        overridden = {o["name"]: o["fields"] for o in diff["entry_rules"]["overridden"]}
        assert set(overridden) == {"flask_app"}
        assert overridden["flask_app"]["ast_pattern"] == {
            "default": default_pattern,
            "user": "function_call:*.run",
        }

    def test_diff_reports_disabled_rule_and_other_keys(self):
        """`enabled` on a rule and non-rule keys are reported separately."""
        cfg = self._config_from_previous_template()
        for rule in cfg["entry_rules"]:
            if rule["name"] == "typer_app":
                rule["enabled"] = False
        cfg["lang"] = "zh_CN"
        self._write_config(cfg)

        diff = self.cm.diff()

        overridden = {o["name"]: o["fields"] for o in diff["entry_rules"]["overridden"]}
        assert overridden["typer_app"]["enabled"] == {"default": True, "user": False}
        assert diff["keys"]["lang"] == {"default": "system", "user": "zh_CN"}
        assert "version" not in diff["keys"]  # reported under template_version

    # ── one-time notice ───────────────────────────────────────

    def test_notice_returned_once_then_never_again(self):
        """The template-update notice is delivered exactly once."""
        self._write_config(self._config_from_previous_template())
        before = self._read_config_bytes()

        notice = self.cm.pending_template_notice()

        assert notice == {"user": 1, "current": DEFAULT_CONFIG["version"]}
        assert self.cm.pending_template_notice() is None
        assert self._read_config_bytes() == before  # config.json untouched
        assert os.path.isfile(self._notice_marker_path())

    def test_notice_silent_when_template_is_current(self):
        """No notice when config.json already records the current version."""
        self._write_config(json.loads(json.dumps(DEFAULT_CONFIG)))

        assert self.cm.pending_template_notice() is None
        assert not os.path.isfile(self._notice_marker_path())

    def test_notice_silent_without_config_file(self):
        """No notice (and no directory) when the project has no config yet."""
        assert self.cm.pending_template_notice() is None
        assert not os.path.exists(os.path.join(self.tmpdir, ".graphlint"))

    def test_notice_silent_for_config_without_version(self):
        """A hand-written config with no version key is not announced."""
        self._write_config({"lang": "en"})

        assert self.cm.pending_template_notice() is None
        assert self.cm.template_version_status()["user"] is None
