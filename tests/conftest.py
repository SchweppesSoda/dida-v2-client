import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    def load(name: str):
        return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))

    return load
