from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    config = deepcopy(yaml.safe_load((ROOT / "config/base.yaml").read_text()))
    # Tests must not inherit a workstation's optional commercial solver preference.
    config["solver"].update(backend="highs", threads=4)
    return config


@pytest.fixture
def plants():
    return pd.read_csv(ROOT / "config/plants.csv")
