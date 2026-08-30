from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_csv() -> Path:
    return FIXTURES / "suburbs-sample.csv"
