from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture():
    def read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return read
