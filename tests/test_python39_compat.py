import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_package_imports_under_supported_python39():
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is unavailable")
    assert uv is not None
    found = subprocess.run([uv, "python", "find", "3.9"], capture_output=True, text=True)
    if found.returncode != 0:
        pytest.skip("Python 3.9 is unavailable")
    python = found.stdout.strip()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")

    result = subprocess.run(
        [python, "-c", "import dida_v2_client; print(dida_v2_client.SyncSnapshot)"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
