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
        assert config2["version"] == 1
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
        assert config["version"] == 1  # From defaults
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
