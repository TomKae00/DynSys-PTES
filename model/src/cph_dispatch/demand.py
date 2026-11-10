"""Weather-adjusted HTF demand: transfer an hourly demand profile to another year.

Daily mean demand is fitted as a base load plus a heating term proportional to the
heating degrees below a fitted heating limit. The fit is applied to the target year's
daily temperatures, and each day receives the source year's average hourly shape for
its month and day type (weekday, Saturday, Sunday). The result can be scaled to a
known annual total, so that the level follows the data and the pattern the weather.
"""

import numpy as np
import pandas as pd

LOCAL = "Etc/GMT-1"  # fixed CET, as for the inherited naive profiles


def _local_days(index):
    return index.tz_convert(LOCAL).normalize()


def _day_type(days):
    weekday = days.dayofweek
    return np.where(weekday < 5, "weekday", np.where(weekday == 5, "saturday", "sunday"))


def fit_daily(demand, temperature, limits=np.arange(10.0, 20.01, 0.25)):
    """Least-squares fit of daily demand = base + slope * max(limit - T, 0)."""
    demand, temperature = demand.align(temperature, join="inner")
    best = None
    for limit in limits:
        degrees = np.maximum(limit - temperature.to_numpy(), 0.0)
        design = np.column_stack([np.ones_like(degrees), degrees])
        coefficients, *_ = np.linalg.lstsq(design, demand.to_numpy(), rcond=None)
        error = float(((design @ coefficients - demand.to_numpy()) ** 2).sum())
        if best is None or error < best[0]:
            best = (error, float(limit), coefficients)
    error, limit, (base, slope) = best
    total = float(((demand - demand.mean()) ** 2).sum())
    return {
        "base_mw": float(base),
        "slope_mw_per_k": float(slope),
        "heating_limit_c": limit,
        "r2": 1 - error / total if total else np.nan,
        "days": int(len(demand)),
    }


def transfer(demand, source_temperature, target_temperature, target_index, *, total_mwh=None):
    """Return the target-year hourly demand (UTC index) and a fit report.

    demand: hourly source-year demand with naive fixed-CET timestamps.
    source_temperature, target_temperature: hourly UTC air temperatures.
    """
    demand = demand.copy()
    demand.index = pd.to_datetime(demand.index).tz_localize(LOCAL).tz_convert("UTC")
    source_days = _local_days(demand.index)
    daily = demand.groupby(source_days).mean()
    source_temp = source_temperature.groupby(_local_days(source_temperature.index)).mean()
    fit = fit_daily(daily, source_temp)

    ratio = demand / daily.reindex(source_days).to_numpy()
    local = demand.index.tz_convert(LOCAL)
    key = pd.MultiIndex.from_arrays([local.month, _day_type(source_days), local.hour])
    shape = ratio.groupby(key).mean()

    target_index = target_index.tz_convert("UTC")
    target_days = _local_days(target_index)
    target_temp = target_temperature.groupby(_local_days(target_temperature.index)).mean()
    missing = pd.Index(target_days.unique()).difference(target_temp.index)
    if len(missing):
        raise ValueError("Target temperature does not cover every target day")
    degrees = np.maximum(fit["heating_limit_c"] - target_temp, 0.0)
    predicted = (fit["base_mw"] + fit["slope_mw_per_k"] * degrees).clip(lower=0.0)
    target_local = target_index.tz_convert(LOCAL)
    target_key = pd.MultiIndex.from_arrays(
        [target_local.month, _day_type(target_days), target_local.hour]
    )
    hourly_shape = pd.Series(shape.reindex(target_key).to_numpy(), index=target_index)
    if hourly_shape.isna().any():
        raise ValueError("Source year lacks an hourly shape for some target month/day type")
    # Each day's shape averages one, so the day keeps its predicted mean.
    hourly_shape = hourly_shape / hourly_shape.groupby(target_days).transform("mean").to_numpy()
    result = hourly_shape * predicted.reindex(target_days).to_numpy()
    unscaled = float(result.sum())
    factor = 1.0 if total_mwh is None else float(total_mwh) / unscaled
    result = (result * factor).rename("htf_demand_mw")
    report = {
        **fit,
        "source_total_mwh": float(demand.sum()),
        "weather_adjusted_total_mwh": unscaled,
        "target_total_mwh": float(result.sum()),
        "scale_factor": factor,
    }
    return result, report
