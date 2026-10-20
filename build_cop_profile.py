#!/usr/bin/env python3
"""Build hourly heat-pump COP profiles for the Høje Taastrup model."""

from pathlib import Path

import numpy as np
import pandas as pd


# --------------------------
# Settings (edit these)
# --------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "Data"

DH_TEMPERATURE_CSV = (
    DATA_DIR / "dh_temperature_profiles_hj_taastrup_2024.csv"
)
OUT_CSV = DATA_DIR / "dh_cop_profiles_hj_taastrup.csv"

# snapshots
START = "2024-01-01 00:00:00"
END   = "2025-01-01 00:00:00"   # exclusive
FREQ  = "h"

# Groundwater source HP temperatures (your assumption)
T_GW_SOURCE_IN_C  = 10.5  # water enters HP from aquifer
T_GW_SOURCE_OUT_C = 4.0   # leaves cooled

# Soil source HP: simple seasonal soil temperature model
SOIL_MEAN_C = 9.0
SOIL_AMP_C = 6.0
SOIL_COLDEST_DOY = 45      # ~mid-Feb
SOIL_DELTA_T_SOURCE = 4.0  # assumed cooling across ground loop

# CITY2 water-water HP source temperatures (same style as GW HP)
T_CITY2_SOURCE_IN_C  = 12.0  # water enters HP from city2 loop / main system
T_CITY2_SOURCE_OUT_C = 8.0   # leaves cooled

# COP model params (same structure as CentralHeatingCopApproximator defaults)
REFRIGERANT = "ammonia"     # "ammonia" or "isobutane"
DELTA_T_PINCH = 2.0
ETA_ISENTROPIC = 0.75
HEAT_LOSS = 0.0
MIN_DELTA_T_LIFT = 5.0


# --------------------------
# Helpers
# --------------------------
def lmtd(Th, Tc):
    """Log-mean temperature difference (vectorized)."""
    Th = np.asarray(Th, dtype=float)
    Tc = np.asarray(Tc, dtype=float)
    if np.any(Th < Tc):
        raise ValueError("t_hot must be >= t_cold for LMTD")
    return np.where(Th == Tc, Th, (Th - Tc) / np.log(Th / Tc))


def soil_temperature_c(times: pd.DatetimeIndex, mean_c, amplitude_c, coldest_doy):
    """Simple sinusoidal soil temperature (°C). Minimum at coldest_doy."""
    doy = times.dayofyear.to_numpy()
    return mean_c - amplitude_c * np.cos(2.0 * np.pi * (doy - coldest_doy) / 365.0)


def load_dh_temperature_profile(
    path: Path,
    snapshots: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Load and validate the hourly DH supply and return temperatures."""
    if not path.exists():
        raise FileNotFoundError(
            f"DH temperature profile not found: {path}\n"
            "Run build_dh_temperature_profile.py first."
        )

    temperatures = pd.read_csv(path)
    required_columns = {
        "time",
        "dh_supply_temperature_c",
        "dh_return_temperature_c",
    }
    missing_columns = required_columns.difference(temperatures.columns)
    if missing_columns:
        raise ValueError(
            f"{path} is missing columns: {sorted(missing_columns)}"
        )

    index = pd.DatetimeIndex(pd.to_datetime(temperatures["time"], errors="raise"))
    if index.tz is not None:
        index = index.tz_convert("UTC").tz_localize(None)

    temperatures = temperatures.set_index(index)
    temperatures.index.name = "snapshot"

    if temperatures.index.has_duplicates:
        duplicated_time = temperatures.index[
            temperatures.index.duplicated()
        ][0]
        raise ValueError(
            f"DH temperature profile contains duplicate time {duplicated_time}."
        )

    temperature_columns = [
        "dh_supply_temperature_c",
        "dh_return_temperature_c",
    ]
    temperatures = temperatures[temperature_columns].apply(
        pd.to_numeric,
        errors="raise",
    )
    temperatures = temperatures.reindex(snapshots)

    if temperatures.isna().any().any():
        missing_times = temperatures.index[temperatures.isna().any(axis=1)]
        raise ValueError(
            f"DH temperature profile is missing {len(missing_times)} required "
            f"hourly rows. First missing time: {missing_times[0]}."
        )

    invalid = (
        temperatures["dh_supply_temperature_c"]
        <= temperatures["dh_return_temperature_c"]
    )
    if invalid.any():
        invalid_time = temperatures.index[invalid][0]
        raise ValueError(
            "DH supply temperature must exceed return temperature. "
            f"First violation: {invalid_time}."
        )

    return temperatures


def cop_central_heating(
    T_sink_out_C, T_sink_in_C,
    T_source_in_C, T_source_out_C,
    refrigerant: str,
    delta_t_pinch: float,
    eta_isentropic: float,
    heat_loss: float,
    min_delta_t_lift: float,
):
    """Flattened CentralHeatingCopApproximator; returns COP with same cutoffs."""
    # unit sanity (same spirit as BaseCopApproximator.celsius_to_kelvin)
    for name, arr in [
        ("T_sink_out_C", T_sink_out_C), ("T_sink_in_C", T_sink_in_C),
        ("T_source_in_C", T_source_in_C), ("T_source_out_C", T_source_out_C),
    ]:
        if np.any(np.asarray(arr) > 200):
            raise ValueError(f"{name} > 200°C. Check units (should be °C).")

    # Kelvin
    T_sink_out = np.asarray(T_sink_out_C, dtype=float) + 273.15
    T_sink_in  = np.asarray(T_sink_in_C,  dtype=float) + 273.15
    T_src_in   = np.asarray(T_source_in_C, dtype=float) + 273.15
    T_src_out  = np.asarray(T_source_out_C, dtype=float) + 273.15

    # mean temps and lifts
    T_sink_mean = lmtd(T_sink_out, T_sink_in)
    T_src_mean  = lmtd(T_src_in, T_src_out)

    dT_mean = T_sink_mean - T_src_mean
    dT_lift = T_sink_out - T_src_in

    COP_lorenz = T_sink_mean / dT_mean

    # approximations
    dT_sink = T_sink_out - T_sink_in
    dT_ref_src = (T_src_in - T_src_out) / 2.0
    X = (T_sink_out - T_src_out + 2.0 * delta_t_pinch)

    if refrigerant == "ammonia":
        a1, b1, c1 = 0.2, 0.2, 0.016
        a2, b2, c2 = 0.0014, -0.0015, 0.039
    elif refrigerant == "isobutane":
        a1, b1, c1 = -0.0011, 0.3, 2.4
        a2, b2, c2 = 0.0035, -0.0033, 0.053
    else:
        raise ValueError("REFRIGERANT must be 'ammonia' or 'isobutane'.")

    dT_ref_sink = a1 * X + b1 * dT_sink + c1
    r = a2 * X + b2 * dT_sink + c2

    factor = (1.0 + (dT_ref_sink + delta_t_pinch) / T_sink_mean) / (
        1.0 + (dT_ref_sink + dT_ref_src + 2.0 * delta_t_pinch) / dT_mean
    )

    COP = (
        COP_lorenz * factor * eta_isentropic * (1.0 - r)
        + (1.0 - eta_isentropic)
        - heat_loss
    )

    # cutoffs like in the original code path
    COP = np.where(dT_lift < min_delta_t_lift, 0.0, COP)  # _approximate_cop
    COP = np.where(COP < 1.0, 0.0, COP)                  # BaseCopApproximator.cop
    return COP


def main():
    # snapshots
    snapshots = pd.date_range(start=START, end=END, freq=FREQ, inclusive="left")

    # Hourly sink temperatures from the historical HT steering curve and the
    # assumed fixed 50 degC return temperature.
    dh_temperatures = load_dh_temperature_profile(
        DH_TEMPERATURE_CSV,
        snapshots,
    )
    T_sink_out = dh_temperatures[
        "dh_supply_temperature_c"
    ].to_numpy(dtype=float)
    T_sink_in = dh_temperatures[
        "dh_return_temperature_c"
    ].to_numpy(dtype=float)

    # groundwater temps as arrays
    T_gw_in  = np.full(len(snapshots), T_GW_SOURCE_IN_C, dtype=float)
    T_gw_out = np.full(len(snapshots), T_GW_SOURCE_OUT_C, dtype=float)

    cop_gw = cop_central_heating(
        T_sink_out_C=T_sink_out,
        T_sink_in_C=T_sink_in,
        T_source_in_C=T_gw_in,
        T_source_out_C=T_gw_out,
        refrigerant=REFRIGERANT,
        delta_t_pinch=DELTA_T_PINCH,
        eta_isentropic=ETA_ISENTROPIC,
        heat_loss=HEAT_LOSS,
        min_delta_t_lift=MIN_DELTA_T_LIFT,
    )

    # soil temps as arrays
    T_soil = soil_temperature_c(
        snapshots, mean_c=SOIL_MEAN_C, amplitude_c=SOIL_AMP_C, coldest_doy=SOIL_COLDEST_DOY
    )
    T_soil_in  = T_soil
    T_soil_out = T_soil - SOIL_DELTA_T_SOURCE

    cop_soil = cop_central_heating(
        T_sink_out_C=T_sink_out,
        T_sink_in_C=T_sink_in,
        T_source_in_C=T_soil_in,
        T_source_out_C=T_soil_out,
        refrigerant=REFRIGERANT,
        delta_t_pinch=DELTA_T_PINCH,
        eta_isentropic=ETA_ISENTROPIC,
        heat_loss=HEAT_LOSS,
        min_delta_t_lift=MIN_DELTA_T_LIFT,
    )

    # CITY2 water-water HP temps as arrays (same style as GW HP)
    T_city2_in  = np.full(len(snapshots), T_CITY2_SOURCE_IN_C, dtype=float)
    T_city2_out = np.full(len(snapshots), T_CITY2_SOURCE_OUT_C, dtype=float)

    cop_city2 = cop_central_heating(
        T_sink_out_C=T_sink_out,
        T_sink_in_C=T_sink_in,
        T_source_in_C=T_city2_in,
        T_source_out_C=T_city2_out,
        refrigerant=REFRIGERANT,
        delta_t_pinch=DELTA_T_PINCH,
        eta_isentropic=ETA_ISENTROPIC,
        heat_loss=HEAT_LOSS,
        min_delta_t_lift=MIN_DELTA_T_LIFT,
    )

    df = pd.DataFrame(
        {
            "GW_HP": cop_gw,
            "SOIL_HP": cop_soil,
            "CITY2_HP": cop_city2,
        },
        index=snapshots,
    )
    df.index.name = "snapshot"
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV)

    print(f"Read hourly DH temperatures from {DH_TEMPERATURE_CSV}")
    print(f"Wrote {OUT_CSV}")
    print(df.describe().T[["min", "mean", "max"]])


if __name__ == "__main__":
    main()
