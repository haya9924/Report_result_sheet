from pathlib import Path

import pytest

from resultsheet.schema import load_definition
from resultsheet.store import get_template

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def density_def():
    return load_definition(get_template("density"))


@pytest.fixture
def free_fall_def():
    return load_definition(get_template("free_fall"))


@pytest.fixture
def free_fall_data():
    """h = 4.9 t^2 (g=9.8) にほぼ沿った測定データ。"""
    return {
        "drops": {
            "columns": ["h", "t"],
            "rows": [
                [0.5, 0.320],
                [1.0, 0.452],
                [1.5, 0.553],
                [2.0, 0.639],
                [2.5, 0.714],
            ],
        }
    }
