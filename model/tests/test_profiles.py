import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cph_dispatch.profiles import apply_profiles, build_profiles, cop_central_heating, lmtd


def legacy_module(name):
    path = Path(__file__).resolve().parents[2] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_temperature_and_cop_equations_match_initial_scripts(monkeypatch):
    old_temperature = legacy_module("build_dh_temperature_profile")
    old_cop = legacy_module("build_cop_profile")
    snapshots = old_temperature.model_snapshots(2024)
    required = pd.date_range(snapshots[0] - pd.Timedelta(hours=23), snapshots[-1], freq="h")
    # Cold/warm periods exercise the sloped curves and summer minimum.
    ambient = pd.Series(
        10 + 20 * np.sin(np.arange(len(required)) / 1000),
        index=required,
        name="ambient_temperature_c",
    )
    monkeypatch.setattr(old_temperature, "obtain_ambient_temperature", lambda year: ambient)
    old = old_temperature.build_temperature_profile(2024)
    new = build_profiles(ambient, snapshots)
    np.testing.assert_allclose(new[old.columns], old, atol=1e-12)
    for column, source_in, source_out in [("city2_cop", 12, 8), ("groundwater_cop", 10.5, 4)]:
        expected = old_cop.cop_central_heating(
            old.dh_supply_temperature_c,
            old.dh_return_temperature_c,
            source_in,
            source_out,
            "ammonia",
            2,
            0.75,
            0,
            5,
        )
        np.testing.assert_allclose(new[column], expected, atol=1e-12)
    soil = old_cop.soil_temperature_c(snapshots, 9, 6, 45)
    np.testing.assert_allclose(
        new.soil_cop,
        old_cop.cop_central_heating(
            old.dh_supply_temperature_c,
            old.dh_return_temperature_c,
            soil,
            soil - 4,
            "ammonia",
            2,
            0.75,
            0,
            5,
        ),
        atol=1e-12,
    )
    np.testing.assert_allclose(lmtd([300, 310], [300, 300]), [300, 10 / np.log(310 / 300)])


def test_profiles_use_true_utc_hours_and_require_warmup(tmp_path):
    snapshots = pd.date_range("2023-12-31T23:00Z", periods=48, freq="h")
    required = pd.date_range(snapshots[0] - pd.Timedelta(hours=23), snapshots[-1], freq="h")
    ambient = pd.Series(np.arange(len(required)) / 10, index=required)
    with pytest.raises(ValueError, match="23 preceding"):
        build_profiles(ambient.iloc[1:], snapshots)
    profiles = build_profiles(ambient, snapshots)
    assert profiles.ambient_temperature_filtered_24h_c.iloc[0] == pytest.approx(1.15)
    path = tmp_path / "profiles.csv"
    profiles.to_csv(path)
    frame = pd.DataFrame({"city2_cop": 99.0}, index=snapshots)
    actual = apply_profiles(frame, path)
    np.testing.assert_allclose(actual.city2_cop, profiles.city2_cop)
    profiles.iloc[1:].to_csv(path)
    with pytest.raises(ValueError, match="every requested UTC hour"):
        apply_profiles(frame, path)


def test_cop_cutoff_preserved():
    assert cop_central_heating(60, 50, 58, 54, min_delta_t_lift=5) == 0
