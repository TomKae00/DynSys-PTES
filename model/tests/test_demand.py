import numpy as np
import pandas as pd

from cph_dispatch.demand import fit_daily, transfer


def _temperature(year, offset=0.0):
    index = pd.date_range(f"{year - 1}-12-31 23:00", f"{year}-12-31 23:00", freq="h", tz="UTC")
    day = index.dayofyear.to_numpy()
    values = 9 - 8 * np.cos(2 * np.pi * (day - 20) / 366) + 2 * np.sin(2 * np.pi * index.hour / 24)
    return pd.Series(values + offset, index=index)


def test_fit_recovers_degree_model():
    temperature = pd.Series(np.linspace(-5, 25, 200))
    demand = 12 + 3.0 * np.maximum(16 - temperature, 0)
    fit = fit_daily(demand, temperature)
    assert abs(fit["heating_limit_c"] - 16) < 1e-9
    assert abs(fit["base_mw"] - 12) < 1e-6 and abs(fit["slope_mw_per_k"] - 3) < 1e-6


def test_transfer_follows_target_weather_and_total():
    source_temperature = _temperature(2019)
    local = pd.date_range("2019-01-01", periods=8760, freq="h")
    utc = local.tz_localize("Etc/GMT-1").tz_convert("UTC")
    daily = source_temperature.groupby(source_temperature.index.tz_convert("Etc/GMT-1").normalize()).mean()
    level = 10 + 2.5 * np.maximum(16 - daily.reindex(utc.tz_convert("Etc/GMT-1").normalize()).to_numpy(), 0)
    shape = 1 + 0.1 * np.sin(2 * np.pi * (local.hour - 7) / 24)
    demand = pd.Series(level * shape, index=local)
    target_index = pd.date_range("2024-01-01", "2024-12-31 23:00", freq="h", tz="UTC")
    colder = _temperature(2024, offset=-2.0)
    result, report = transfer(demand, source_temperature, colder, target_index)
    assert report["r2"] > 0.999
    # A colder year needs more heat; with a total given, the level is matched exactly.
    assert report["weather_adjusted_total_mwh"] > demand.sum() * 1.05
    scaled, report = transfer(demand, source_temperature, colder, target_index, total_mwh=377274)
    np.testing.assert_allclose(scaled.sum(), 377274)
    assert scaled.index.equals(target_index) and (scaled > 0).all()
