from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_TEST = ROOT / "tests" / "js" / "analytics_runtime.test.js"


def test_conversion_analytics_javascript_runtime_contracts():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable")

    result = subprocess.run(
        [node, "--test", str(RUNTIME_TEST)],
        cwd=ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )

    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert result.returncode == 0, output
