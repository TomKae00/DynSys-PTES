"""Historical HTF steering curves and Lorenz COP approximation, on actual UTC hours.

The equations/defaults preserve build_dh_temperature_profile.py and
build_cop_profile.py. They are modelling assumptions, not measured temperatures/COPs.
"""

import numpy as np
import pandas as pd
import xarray as xr

NETPOINTS = {
    "birkelunden": (66.0, 74.0, 16.0),
    "klovtoftegade": (68.0, 78.0, 16.0),
    "egevangshusene": (63.0, 73.0, 16.0),
}


def hourly_series(series):
    """Naive source timestamps explicitly mean UTC, as in the original scripts."""
    series = pd.to_numeric(series, errors="raise").copy()
    series.index = pd.to_datetime(series.index, utc=True)
    series = series.sort_index()
    if series.index.has_duplicates or not np.isfinite(series).all():
        raise ValueError("Temperature input must be unique and finite")
    return series


def read_era5(paths, *, latitude=55.65, longitude=12.27):
    """Prefer the nearest complete ERA5 land cell, preserving the legacy selection."""
    parts = []
    for path in paths:
        with xr.open_dataset(path) as dataset:
            temperature = dataset["t2m"]
            lat = next(k for k in ("latitude", "lat") if k in temperature.coords)
            lon = next(k for k in ("longitude", "lon") if k in temperature.coords)
            time = next(k for k in ("valid_time", "time") if k in temperature.coords)
            candidates = []
            for y in np.atleast_1d(temperature[lat]):
                for x in np.atleast_1d(temperature[lon]):
                    s = temperature.sel({lat: float(y), lon: float(x)}).to_series()
                    if isinstance(s.index, pd.MultiIndex):
                        s = s.groupby(level=time).first()
                    distance = (float(y) - latitude) ** 2 + (float(x) - longitude) ** 2
                    candidates.append((int(s.isna().sum()), distance, s))
            parts.append(min(candidates, key=lambda item: item[:2])[2].copy())
    joined = pd.concat(parts).sort_index()
    if joined.index.has_duplicates:
        # Overlapping files are allowed only if their shared values agree.
        if (joined.groupby(level=0).max() - joined.groupby(level=0).min()).abs().max() > 1e-8:
            raise ValueError("Conflicting overlapping ERA5 samples")
        joined = joined[~joined.index.duplicated()]
    return hourly_series(joined - 273.15)


def lmtd(hot, cold):
    hot, cold = np.broadcast_arrays(np.asarray(hot, float), np.asarray(cold, float))
    if np.any(hot < cold) or np.any(cold <= 0):
        raise ValueError("LMTD requires positive Kelvin temperatures with hot >= cold")
    result = hot.copy()
    different = hot != cold
    np.divide(hot - cold, np.log(hot / cold), out=result, where=different)
    return result


def cop_central_heating(
    T_sink_out_C,
    T_sink_in_C,
    T_source_in_C,
    T_source_out_C,
    refrigerant="ammonia",
    delta_t_pinch=2.0,
    eta_isentropic=0.75,
    heat_loss=0.0,
    min_delta_t_lift=5.0,
):
    """Same flattened CentralHeatingCopApproximator and cutoffs as the initial model."""
    arrays = [
        np.asarray(v, float) for v in (T_sink_out_C, T_sink_in_C, T_source_in_C, T_source_out_C)
    ]
    if any((~np.isfinite(v)).any() or (v > 200).any() or (v <= -273.15).any() for v in arrays):
        raise ValueError("COP temperatures must be finite Celsius values in (-273.15,200]")
    sink_out, sink_in, source_in, source_out = [v + 273.15 for v in arrays]
    sink_mean, source_mean = lmtd(sink_out, sink_in), lmtd(source_in, source_out)
    difference = sink_mean - source_mean
    cutoff = sink_out - source_in < min_delta_t_lift
    if np.any((difference <= 0) & ~cutoff):
        raise ValueError("COP approximation requires a positive mean temperature lift")
    # The original approximation returns zero below the lift cutoff, even where
    # an intermediate Lorenz expression would be singular or negative.
    difference = np.where(cutoff, 1.0, difference)
    sink_drop = sink_out - sink_in
    source_drop = (source_in - source_out) / 2.0
    lift = sink_out - source_out + 2.0 * delta_t_pinch
    if refrigerant == "ammonia":
        a1, b1, c1, a2, b2, c2 = 0.2, 0.2, 0.016, 0.0014, -0.0015, 0.039
    elif refrigerant == "isobutane":
        a1, b1, c1, a2, b2, c2 = -0.0011, 0.3, 2.4, 0.0035, -0.0033, 0.053
    else:
        raise ValueError("Refrigerant must be ammonia or isobutane")
    reference_drop = a1 * lift + b1 * sink_drop + c1
    r = a2 * lift + b2 * sink_drop + c2
    factor = (1 + (reference_drop + delta_t_pinch) / sink_mean) / (
        1 + (reference_drop + source_drop + 2 * delta_t_pinch) / difference
    )
    cop = (
        sink_mean / difference * factor * eta_isentropic * (1 - r)
        + (1 - eta_isentropic)
        - heat_loss
    )
    return np.where(cutoff | (cop < 1), 0.0, cop)


def build_profiles(
    ambient, snapshots, *, return_c=50.0, margin_c=0.0, minimum_supply_c=None, maximum_supply_c=None
):
    """Build temperature and three COP profiles with 23 prior hours of warm-up."""
    if (
        snapshots.tz is None
        or len(snapshots) < 2
        or not np.all(np.diff(snapshots.asi8) == 3600 * 10**9)
    ):
        raise ValueError("Profiles need consecutive timezone-aware hourly snapshots")
    snapshots = snapshots.tz_convert("UTC")
    required = pd.date_range(snapshots[0] - pd.Timedelta(hours=23), snapshots[-1], freq="h")
    ambient = hourly_series(ambient).reindex(required)
    if ambient.isna().any():
        raise ValueError("Ambient input must cover the horizon and 23 preceding UTC hours")
    filtered = ambient.rolling(24, min_periods=24).mean().reindex(snapshots)
    d = pd.DataFrame(
        {
            "ambient_temperature_c": ambient.reindex(snapshots),
            "ambient_temperature_filtered_24h_c": filtered,
        }
    )
    for name, (minimum, at_zero, breakpoint) in NETPOINTS.items():
        d[f"netpoint_{name}_temperature_c"] = np.maximum(
            minimum, at_zero - (at_zero - minimum) / breakpoint * filtered
        )
    d["critical_netpoint_temperature_c"] = d.filter(like="netpoint_").max(axis=1)
    supply = d.critical_netpoint_temperature_c + margin_c
    if minimum_supply_c is not None:
        supply = supply.clip(lower=minimum_supply_c)
    if maximum_supply_c is not None:
        supply = supply.clip(upper=maximum_supply_c)
    if (supply <= return_c).any():
        raise ValueError("DH supply must exceed return temperature")
    d["dh_supply_temperature_c"] = supply
    d["dh_return_temperature_c"] = return_c
    d["dh_temperature_difference_c"] = supply - return_c
    soil = 9.0 - 6.0 * np.cos(2 * np.pi * (snapshots.dayofyear.to_numpy() - 45) / 365.0)
    for column, source_in, source_out in [
        ("city2_cop", 12.0, 8.0),
        ("groundwater_cop", 10.5, 4.0),
        ("soil_cop", soil, soil - 4.0),
    ]:
        d[column] = cop_central_heating(supply, return_c, source_in, source_out)
    d.index.name = "timestamp"
    return d


def apply_profiles(frame, path):
    """Replace templates by actual UTC profiles; missing edge hours are errors."""
    profiles = pd.read_csv(path, index_col=0)
    profiles.index = pd.to_datetime(profiles.index, utc=True)
    if profiles.index.has_duplicates:
        raise ValueError("Duplicate local profile timestamps")
    required = [
        "city2_cop",
        "groundwater_cop",
        "dh_supply_temperature_c",
        "dh_return_temperature_c",
    ]
    aligned = profiles.reindex(frame.index)
    if not np.isfinite(aligned[required]).all().all():
        raise ValueError("Local profiles must cover every requested UTC hour, without filling")
    result = frame.copy()
    for column in profiles:
        result[column] = aligned[column]
    return result
