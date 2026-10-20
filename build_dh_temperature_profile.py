#!/usr/bin/env python3
"""Build hourly Høje Taastrup DH temperature profiles.

The script:
1. obtains hourly ERA5-Land 2 m ambient temperature for Høje Taastrup;
2. calculates the 24-hour moving-average temperature used by the historical
   Høje Taastrup PRESS controller;
3. evaluates the three historical critical-net-point steering curves;
4. uses the highest curve as a provisional local DH supply-temperature proxy;
5. applies a fixed district-heating return temperature of 50 degC; and
6. exports one hourly CSV for use in the COP calculation.

The steering-curve parameters are taken from Table 8.2 of:
T. S. Nielsen and H. Madsen, "Predictive control of supply temperature in
district heating systems", IMM-TR-2002-23 (2002).
https://www2.imm.dtu.dk/pubdb/edoc/imm1727.ps

ERA5-Land source:
https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land

Requirements
------------
    pip install cdsapi numpy pandas xarray netcdf4

The Copernicus Climate Data Store API must be configured before downloading:
https://cds.climate.copernicus.eu/how-to-api

If a local ambient-temperature CSV is already available, set
AMBIENT_TEMPERATURE_CSV below. It must contain the columns ``time`` and
``temperature_c``. In that case, cdsapi is not needed.
"""

from __future__ import annotations

import calendar
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


# -----------------------------------------------------------------------------
# Settings
# -----------------------------------------------------------------------------
YEAR = 2024

DATA_DIR = Path("Data")
OUTPUT_FILE = DATA_DIR / f"dh_temperature_profiles_hj_taastrup_{YEAR}.csv"

# Optional alternative to ERA5-Land. Expected columns: time, temperature_c.
AMBIENT_TEMPERATURE_CSV: Path | None = None

# Approximate Høje Taastrup coordinates. ERA5-Land is sampled at the nearest
# grid point, so small coordinate changes within Høje Taastrup have no effect.
LATITUDE = 55.65
LONGITUDE = 12.27

# Requested modelling assumption.
DH_RETURN_TEMPERATURE_C = 50.0

# The historical curves describe minimum temperatures at critical net-points.
# For now, the highest net-point curve is used directly as the local DH supply
# temperature proxy. Change this value after calibrating network temperature
# loss against measured HTF supply and net-point temperatures.
NETWORK_TEMPERATURE_MARGIN_C = 0.0

# Optional physical/operational bounds. Keep as None until defensible current
# HTF values are available.
MIN_DH_SUPPLY_TEMPERATURE_C: float | None = None
MAX_DH_SUPPLY_TEMPERATURE_C: float | None = None

# Final critical-net-point curve parameters used in Høje Taastrup from May 1996
# onward (Table 8.2 of IMM-TR-2002-23).
HT_NETPOINT_CURVES = {
    "Birkelunden": {
        "minimum_temperature_c": 66.0,
        "temperature_at_0c_ambient_c": 74.0,
        "ambient_breakpoint_c": 16.0,
    },
    "Klovtoftegade": {
        "minimum_temperature_c": 68.0,
        "temperature_at_0c_ambient_c": 78.0,
        "ambient_breakpoint_c": 16.0,
    },
    "Egevangshusene": {
        "minimum_temperature_c": 63.0,
        "temperature_at_0c_ambient_c": 73.0,
        "ambient_breakpoint_c": 16.0,
    },
}


# -----------------------------------------------------------------------------
# Time-index helpers
# -----------------------------------------------------------------------------
def model_snapshots(year: int) -> pd.DatetimeIndex:
    """Return all hourly UTC snapshots for the selected calendar year."""
    return pd.date_range(
        start=f"{year}-01-01 00:00:00",
        end=f"{year}-12-31 23:00:00",
        freq="h",
        tz="UTC",
    )


def expected_hours(year: int) -> int:
    """Return 8,784 hours for leap years and 8,760 otherwise."""
    return 8784 if calendar.isleap(year) else 8760


def normalize_utc_index(series: pd.Series, name: str) -> pd.Series:
    """Return a sorted, numeric series with a timezone-aware UTC index."""
    series = series.copy()
    index = pd.to_datetime(series.index, errors="raise")

    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")

    series.index = index
    series = pd.to_numeric(series, errors="raise").sort_index()

    if series.index.has_duplicates:
        duplicates = series.index[series.index.duplicated()].unique()
        raise ValueError(
            f"{name} contains duplicate timestamps, for example {duplicates[0]}."
        )

    if series.isna().any():
        raise ValueError(f"{name} contains missing values.")

    series.name = name
    return series


# -----------------------------------------------------------------------------
# Ambient-temperature input
# -----------------------------------------------------------------------------
def download_era5_land_file(
    target: Path,
    year: int,
    months: list[str],
    days: list[str],
) -> None:
    """Download hourly ERA5-Land 2 m temperature for a small local area."""
    try:
        import cdsapi
    except ImportError as exc:
        raise RuntimeError(
            "cdsapi is required to download ERA5-Land data. Install it with "
            "'pip install cdsapi' or provide AMBIENT_TEMPERATURE_CSV."
        ) from exc

    target.parent.mkdir(parents=True, exist_ok=True)

    request = {
        "variable": ["2m_temperature"],
        "year": [str(year)],
        "month": months,
        "day": days,
        "time": [f"{hour:02d}:00" for hour in range(24)],
        "data_format": "netcdf",
        "download_format": "unarchived",
        # ERA5 area order: north, west, south, east.
        "area": [
            LATITUDE + 0.05,
            LONGITUDE - 0.05,
            LATITUDE - 0.05,
            LONGITUDE + 0.05,
        ],
    }

    print(f"Downloading ERA5-Land data to {target} ...")
    cdsapi.Client().retrieve(
        "reanalysis-era5-land",
        request,
        str(target),
    )


def select_nearest_era5_point(dataset: Any, source: Path) -> Any:
    """Select the closest complete ERA5-Land grid-point time series."""
    if "t2m" not in dataset:
        raise ValueError(
            f"ERA5-Land file does not contain 't2m'. Variables: {list(dataset)}"
        )

    temperature = dataset["t2m"]

    latitude_name = next(
        (name for name in ("latitude", "lat") if name in temperature.coords),
        None,
    )
    longitude_name = next(
        (name for name in ("longitude", "lon") if name in temperature.coords),
        None,
    )

    time_name = next(
        (name for name in ("valid_time", "time") if name in temperature.coords),
        None,
    )
    if time_name is None:
        raise ValueError(
            f"Could not identify the time coordinate in {source}. "
            f"Coordinates: {list(temperature.coords)}"
        )

    if latitude_name is not None and longitude_name is not None:
        latitude_values = np.atleast_1d(temperature[latitude_name].values)
        longitude_values = np.atleast_1d(temperature[longitude_name].values)

        candidates: list[tuple[int, float, float, float, Any]] = []

        for latitude in latitude_values:
            for longitude in longitude_values:
                candidate = temperature.sel(
                    {
                        latitude_name: latitude,
                        longitude_name: longitude,
                    }
                )
                candidate_series = candidate.to_series()

                # Some CDS files contain an additional singleton or version
                # dimension. Collapse it by retaining the first valid value
                # for each timestamp before checking completeness.
                if isinstance(candidate_series.index, pd.MultiIndex):
                    if time_name not in candidate_series.index.names:
                        raise ValueError(
                            f"Unexpected ERA5-Land dimensions in {source}: "
                            f"{candidate_series.index.names}"
                        )
                    candidate_series = candidate_series.groupby(
                        level=time_name
                    ).first()

                missing_count = int(candidate_series.isna().sum())
                distance_squared = (
                    (float(latitude) - LATITUDE) ** 2
                    + (float(longitude) - LONGITUDE) ** 2
                )
                candidates.append(
                    (
                        missing_count,
                        distance_squared,
                        float(latitude),
                        float(longitude),
                        candidate,
                    )
                )

        # Prefer a complete nearby land cell over a slightly closer cell with
        # missing values. The requested area covers only about 0.1 degrees.
        candidates.sort(key=lambda item: (item[0], item[1]))
        missing_count, _, latitude, longitude, temperature = candidates[0]

        if missing_count:
            print(
                f"Warning: {source} still contains {missing_count} missing "
                f"hourly values at the best available grid point "
                f"({latitude:.2f}, {longitude:.2f})."
            )

    return temperature.squeeze(drop=True)


def read_era5_land_temperature(paths: list[Path]) -> pd.Series:
    """Read and combine ERA5-Land files, converting Kelvin to degC."""
    try:
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError(
            "xarray is required to read ERA5-Land NetCDF files. Install it "
            "with 'pip install xarray netcdf4' or provide "
            "AMBIENT_TEMPERATURE_CSV."
        ) from exc

    series_parts: list[pd.Series] = []

    for path in paths:
        with xr.open_dataset(path) as dataset:
            temperature = select_nearest_era5_point(dataset, path).load()

        time_name = next(
            (name for name in ("valid_time", "time") if name in temperature.coords),
            None,
        )
        if time_name is None:
            raise ValueError(
                f"Could not identify the time coordinate in {path}. "
                f"Coordinates: {list(temperature.coords)}"
            )

        part = temperature.to_series()
        if isinstance(part.index, pd.MultiIndex):
            if time_name not in part.index.names:
                raise ValueError(
                    f"Unexpected ERA5-Land index dimensions in {path}: "
                    f"{part.index.names}"
                )
            part = part.groupby(level=time_name).first()

        if part.isna().any():
            missing_times = part.index[part.isna()]
            raise ValueError(
                f"{path} contains {len(missing_times)} missing ERA5-Land "
                f"temperature values at the best available grid point. "
                f"First missing timestamp: {missing_times[0]}. Delete only "
                f"this file and rerun the script to download it again."
            )

        part.index = pd.to_datetime(part.index, utc=True)
        series_parts.append(part)

    temperature_k = pd.concat(series_parts).sort_index()
    temperature_k = temperature_k[~temperature_k.index.duplicated(keep="first")]

    temperature_c = temperature_k - 273.15
    return normalize_utc_index(
        temperature_c,
        "ambient_temperature_c",
    )


def load_ambient_temperature_csv(path: Path) -> pd.Series:
    """Load a user-provided hourly ambient-temperature CSV."""
    frame = pd.read_csv(path)
    required_columns = {"time", "temperature_c"}
    missing = required_columns.difference(frame.columns)
    if missing:
        raise ValueError(
            f"Ambient-temperature CSV is missing columns: {sorted(missing)}"
        )

    series = frame.set_index("time")["temperature_c"]
    return normalize_utc_index(series, "ambient_temperature_c")


def obtain_ambient_temperature(year: int) -> pd.Series:
    """Load a provided CSV or obtain the required ERA5-Land temperature."""
    if AMBIENT_TEMPERATURE_CSV is not None:
        if not AMBIENT_TEMPERATURE_CSV.exists():
            raise FileNotFoundError(AMBIENT_TEMPERATURE_CSV)
        return load_ambient_temperature_csv(AMBIENT_TEMPERATURE_CSV)

    previous_day_file = DATA_DIR / f"era5_land_t2m_{year - 1}_12_31.nc"
    if not previous_day_file.exists() or previous_day_file.stat().st_size == 0:
        download_era5_land_file(
            target=previous_day_file,
            year=year - 1,
            months=["12"],
            days=["31"],
        )

    # A complete year in one CDS request exceeds the ERA5-Land request-cost
    # limit. Download one calendar month at a time instead. Keeping separate
    # files also makes the process resumable after an interruption.
    model_year_files: list[Path] = []

    for month in range(1, 13):
        month_file = DATA_DIR / f"era5_land_t2m_{year}_{month:02d}.nc"
        model_year_files.append(month_file)

        if not month_file.exists() or month_file.stat().st_size == 0:
            number_of_days = calendar.monthrange(year, month)[1]
            download_era5_land_file(
                target=month_file,
                year=year,
                months=[f"{month:02d}"],
                days=[f"{day:02d}" for day in range(1, number_of_days + 1)],
            )

    return read_era5_land_temperature(
        [previous_day_file, *model_year_files]
    )


# -----------------------------------------------------------------------------
# Historical Høje Taastrup steering curves
# -----------------------------------------------------------------------------
def calculate_netpoint_curves(
    filtered_ambient_temperature_c: pd.Series,
) -> pd.DataFrame:
    """Calculate the three critical-net-point temperature curves."""
    curves: dict[str, pd.Series] = {}

    for name, parameters in HT_NETPOINT_CURVES.items():
        minimum = parameters["minimum_temperature_c"]
        at_zero = parameters["temperature_at_0c_ambient_c"]
        breakpoint = parameters["ambient_breakpoint_c"]
        slope = (at_zero - minimum) / breakpoint

        curve = np.maximum(
            minimum,
            at_zero - slope * filtered_ambient_temperature_c,
        )
        curves[f"netpoint_{name.lower()}_temperature_c"] = pd.Series(
            curve,
            index=filtered_ambient_temperature_c.index,
        )

    return pd.DataFrame(curves)


def calculate_supply_temperature(
    critical_netpoint_temperature_c: pd.Series,
) -> pd.Series:
    """Convert the governing net-point curve into the supply proxy."""
    supply = (
        critical_netpoint_temperature_c
        + NETWORK_TEMPERATURE_MARGIN_C
    )

    if MIN_DH_SUPPLY_TEMPERATURE_C is not None:
        supply = supply.clip(lower=MIN_DH_SUPPLY_TEMPERATURE_C)

    if MAX_DH_SUPPLY_TEMPERATURE_C is not None:
        supply = supply.clip(upper=MAX_DH_SUPPLY_TEMPERATURE_C)

    supply.name = "dh_supply_temperature_c"
    return supply


def build_temperature_profile(year: int) -> pd.DataFrame:
    """Build and validate the complete hourly DH temperature profile."""
    snapshots = model_snapshots(year)

    # The first model hour requires the preceding 23 hourly observations.
    required_start = snapshots[0] - pd.Timedelta(hours=23)
    required_index = pd.date_range(
        start=required_start,
        end=snapshots[-1],
        freq="h",
        tz="UTC",
    )

    ambient = obtain_ambient_temperature(year).reindex(required_index)

    if ambient.isna().any():
        missing = ambient.index[ambient.isna()]
        raise ValueError(
            f"Ambient-temperature input is missing {len(missing)} required "
            f"hourly values. First missing timestamp: {missing[0]}."
        )

    ambient_filtered = ambient.rolling(
        window=24,
        min_periods=24,
    ).mean()
    ambient_filtered.name = "ambient_temperature_filtered_24h_c"

    ambient = ambient.reindex(snapshots)
    ambient_filtered = ambient_filtered.reindex(snapshots)

    netpoint_curves = calculate_netpoint_curves(ambient_filtered)
    critical_netpoint = netpoint_curves.max(axis=1)
    critical_netpoint.name = "critical_netpoint_temperature_c"

    supply = calculate_supply_temperature(critical_netpoint)
    return_temperature = pd.Series(
        DH_RETURN_TEMPERATURE_C,
        index=snapshots,
        name="dh_return_temperature_c",
    )

    profile = pd.concat(
        [
            ambient,
            ambient_filtered,
            netpoint_curves,
            critical_netpoint,
            supply,
            return_temperature,
        ],
        axis=1,
    )

    profile["dh_temperature_difference_c"] = (
        profile["dh_supply_temperature_c"]
        - profile["dh_return_temperature_c"]
    )

    if len(profile) != expected_hours(year):
        raise ValueError(
            f"Temperature profile has {len(profile)} rows; "
            f"year {year} requires {expected_hours(year)}."
        )

    if profile.isna().any().any():
        missing_columns = profile.columns[profile.isna().any()].tolist()
        raise ValueError(
            f"Temperature profile contains missing values in {missing_columns}."
        )

    if (profile["dh_temperature_difference_c"] <= 0).any():
        bad_time = profile.index[
            profile["dh_temperature_difference_c"] <= 0
        ][0]
        raise ValueError(
            "DH supply temperature must exceed return temperature. "
            f"First violation: {bad_time}."
        )

    # The remaining model inputs currently use timezone-naive UTC timestamps.
    profile.index = profile.index.tz_convert(None)
    profile.index.name = "time"
    return profile


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    profile = build_temperature_profile(YEAR)
    profile.to_csv(OUTPUT_FILE)

    print(f"Wrote {len(profile)} hourly values to {OUTPUT_FILE}")
    print("\nTemperature summary [degC]:")
    print(
        profile[
            [
                "ambient_temperature_c",
                "ambient_temperature_filtered_24h_c",
                "critical_netpoint_temperature_c",
                "dh_supply_temperature_c",
                "dh_return_temperature_c",
                "dh_temperature_difference_c",
            ]
        ].describe().loc[["min", "mean", "max"]]
    )


if __name__ == "__main__":
    main()
