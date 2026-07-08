# -*- coding: utf-8 -*-
"""Large codebase performance tests."""

import os
import tempfile
import time

import pytest


def _make_file(tmpdir, rel_path, content):
    full = os.path.join(tmpdir, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


def create_temp_fixture_files(tmpdir, count=500):
    """Generate count small .py files."""
    for i in range(count):
        content = f"""
def func_{i}():
    return {i}

class Class_{i}:
    def method(self):
        return func_{i}()
"""
        _make_file(tmpdir, f"mod_{i // 50:02d}/file_{i:04d}.py", content)


@pytest.mark.slow
@pytest.mark.timeout(120)
class TestLargeCodebasePerformance:
    """Large codebase performance tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            create_temp_fixture_files(tmpdir, count=500)
            yield

    def test_build_500_files_under_30s(self):
        """Build 500 small .py files in under 30s."""
        from graphlint.api import build

        start = time.time()
        result = build(root_dir=self.tmpdir, force_rebuild=True, parallel=4)
        elapsed = time.time() - start
        assert elapsed < 30.0, f"Build took {elapsed:.1f}s, exceeds 30s limit"
        assert isinstance(result, dict)

    def test_incremental_single_file_under_2s(self):
        """Build 500 files, modify 1, incremental build under 2s."""
        from graphlint.api import build

        # Full build first
        build(root_dir=self.tmpdir, force_rebuild=True, parallel=4)

        # Modify one file
        mod_path = os.path.join(self.tmpdir, "mod_00", "file_0000.py")
        with open(mod_path, "w", encoding="utf-8") as f:
            f.write("def updated_func():\n    return 999\n")

        start = time.time()
        _ = build(root_dir=self.tmpdir, force_rebuild=False, parallel=4)
        elapsed = time.time() - start
        assert elapsed < 2.0, f"Incremental took {elapsed:.1f}s, exceeds 2s limit"

    def test_memory_under_500mb(self):
        """Build 500 files, verify memory <500 MB."""
        import tracemalloc

        tracemalloc.start()
        from graphlint.api import build

        build(root_dir=self.tmpdir, force_rebuild=True, parallel=4)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_mb = peak / (1024 * 1024)
        assert peak_mb < 500, f"Peak memory {peak_mb:.1f}MB, exceeds 500MB limit"
