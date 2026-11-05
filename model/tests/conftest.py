from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    return deepcopy(yaml.safe_load((ROOT / "config/base.yaml").read_text()))


@pytest.fixture
def plants():
    return pd.read_csv(ROOT / "config/plants.csv")
