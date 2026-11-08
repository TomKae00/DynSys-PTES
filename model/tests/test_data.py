import numpy as np
import pandas as pd
import pytest

from cph_dispatch.data import (
    KEYS,
    demo,
    parse_varmelast,
    repair_series,
    seasonal_template,
    year_index,
)
from cph_dispatch.optimisation import build


def test_leap_year_and_dst_are_utc_unique():
    index = year_index(2024)
    assert len(index) == 8784
    assert index.is_unique
    assert (np.diff(index.asi8) == 3600 * 10**9).all()
    local = index.tz_convert("Europe/Copenhagen")
    assert ((local.month == 10) & (local.day == 27) & (local.hour == 2)).sum() == 2


def test_repair_is_opt_in_logged_and_bounded():
    index = pd.date_range("2024-01-01", periods=600, freq="h", tz="UTC")
    s = pd.Series(np.arange(600) + 100.0, index=index)
    s.iloc[250] = np.nan
    s.iloc[300:339] = 0
    with pytest.raises(ValueError, match="use --repair"):
        repair_series(s, positive=True, repair=False, log=[], name="demand")
    log = []
    repaired = repair_series(s, positive=True, repair=True, log=log, name="demand")
    assert len(log) == 40
    assert repaired.iloc[250] == pytest.approx(350)
    assert repaired.iloc[320] == pytest.approx((s.iloc[152] + s.iloc[488]) / 2)
    s.iloc[300:350] = 0
    with pytest.raises(ValueError, match=">48-hour"):
        repair_series(s, positive=True, repair=True, log=[], name="demand")


def test_template_mapping_is_explicit():
    index = pd.date_range("2019-01-01", periods=8760, freq="h")
    s = pd.Series(index.day, index=index)
    mapped = seasonal_template(s, year_index(2024))
    local = year_index(2024).tz_convert("Etc/GMT-1")
    assert np.all(mapped[(local.month == 2) & (local.day == 29)] == 28)
    with pytest.raises(ValueError, match="complete hourly year"):
        seasonal_template(s.drop(s.index[4]), year_index(2024))


def test_bad_time_and_unknown_boundary_are_rejected(config, plants):
    frame = demo(24)
    with pytest.raises(ValueError, match="consecutive UTC"):
        build(frame.drop(frame.index[4]), config, plants)
    config["demand_boundary"] = "net_withdrawals"
    with pytest.raises(ValueError, match="historical HTF metering"):
        build(frame, config, plants)


def test_public_parser_rejects_flags_and_preserves_real_zero_waste():
    rows = [
        {
            "timestamp": str(t),
            "values": [
                {"key": key, "value": 0 if label == "waste_available_mw" else 100, "valueError": 0}
                for label, key in KEYS.items()
            ],
        }
        for t in year_index(2024)
    ]
    rows[100]["values"][0]["valueError"] = 1
    del rows[200]
    with pytest.raises(ValueError, match="use --repair"):
        parse_varmelast({"times": rows}, 2024)
    frame, log = parse_varmelast({"times": rows}, 2024, repair=True)
    assert len(frame) == 8784
    assert len(log) == 4
    assert (frame.waste_available_mw == 0).all()
    assert (frame.regional_demand_mw == 200).all()
