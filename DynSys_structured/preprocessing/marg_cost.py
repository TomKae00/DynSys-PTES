#!/usr/bin/env python3
"""
Create an hourly time series for:
1) Electricity price (DKK/MWh_el) from Elspotprices.csv
2) VEKS monthly puljepris mapped to hourly (DKK/MWh_th)
3) Unbounded marginal heat cost of a stylized wood-chip back-pressure CHP:
      MC_heat(t) = (c_bio + c_var + e_bio*c_CO2)/eta_th
                   - p_el(t)*(eta_el/eta_th)
4) Dynamic external heat price faced by the local system:
      c_DH(t) = max(0, MC_heat(t))

Outputs a CSV with:
time, elspot_dkk_per_mwh_el, veks_price_dkk_per_mwh_th,
mc_heat_chp_unbounded_dkk_per_mwh_th, mc_heat_chp_dkk_per_mwh_th,
spread_veks_minus_mc_over_eta_rt

The bounded dynamic price retains the legacy column name
``mc_heat_chp_dkk_per_mwh_th`` because that is the column read by the PyPSA
model. The monthly VEKS series is retained only as a comparison series and is
not used to construct the dynamic heat price.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


# -----------------------------
# SETTINGS
# -----------------------------
DATA_DIR = Path("Data")

YEAR = 2024

ELEC_CSV = DATA_DIR / "Elspotprices.csv"
SEP = ";"
TIME_COL = "HourUTC"
PRICE_COL = "SpotPriceDKK"

FREQ = "h"
OUT_CSV = DATA_DIR / f"veks_and_mc_heat_chp_{YEAR}_hourly.csv"


# -----------------------------
# VEKS monthly puljepris (same profile for every year)
# -----------------------------
VEKS_KR_PER_GJ = {
    1: 107.46,
    2: 93.38,
    3: 92.61,
    4: 77.63,
    5: 51.79,
    6: 43.82,
    7: 42.42,
    8: 50.69,
    9: 54.61,
    10: 65.07,
    11: 96.07,
    12: 99.95,
}

GJ_PER_MWH = 3.6


# -----------------------------
# Stylized wood-chip back-pressure CHP marginal heat cost parameters
# Units follow the formulation in the model documentation. Fuel, variable O&M,
# and fossil CO2 emissions are specified per MWh of fuel input (MWh_i).
# -----------------------------
BIO_FUEL_DKK_PER_MWH_INPUT = 271.1
CHP_VOM_DKK_PER_MWH_INPUT = 10.6
BIO_FOSSIL_CO2_T_PER_MWH_INPUT = 0.0
CO2_PRICE_DKK_PER_T = 581.0

ETA_TH = 0.83
ETA_EL = 0.29

DYNAMIC_HEAT_PRICE_FLOOR = 0.0
ETA_RT = 0.90


def build_snapshots(year: int, freq: str) -> pd.DatetimeIndex:
    """
    Build snapshots for one full calendar year.
    """
    start = f"{year}-01-01 00:00:00"
    end = f"{year + 1}-01-01 00:00:00"
    return pd.date_range(start=start, end=end, freq=freq, inclusive="left")


def load_elspot_prices_hourly(
    csv_path: Path,
    sep: str,
    time_col: str,
    price_col: str,
    snapshots: pd.DatetimeIndex,
) -> pd.Series:
    """
    Load and align electricity prices to the selected snapshots.
    """
    df = pd.read_csv(csv_path, sep=sep)
    df["time"] = pd.to_datetime(df[time_col])
    df = df.set_index("time").sort_index()

    prices = df[price_col].astype(str).str.replace(",", ".", regex=False)
    prices = pd.to_numeric(prices, errors="coerce")

    prices = prices.reindex(snapshots).ffill().bfill()
    prices.name = "elspot_dkk_per_mwh_el"
    return prices


def build_veks_price_hourly(
    snapshots: pd.DatetimeIndex,
    veks_kr_per_gj: dict[int, float],
) -> pd.Series:
    """
    Map the monthly VEKS puljepris to the selected snapshots.
    The same monthly values are used for every year.
    """
    months = pd.Series(snapshots.month, index=snapshots)
    veks_price = months.map(veks_kr_per_gj).astype(float) * GJ_PER_MWH
    veks_price.name = "veks_price_dkk_per_mwh_th"
    return veks_price


def compute_mc_heat_chp(
    p_el_dkk_per_mwh_el: pd.Series,
    bio_fuel_dkk_per_mwh_input: float,
    chp_vom_dkk_per_mwh_input: float,
    bio_fossil_co2_t_per_mwh_input: float,
    co2_price_dkk_per_t: float,
    eta_th: float,
    eta_el: float,
    dynamic_heat_price_floor: float,
) -> tuple[pd.Series, pd.Series]:
    """
    Compute the unbounded CHP marginal heat cost and bounded external price.

    Fuel price, variable O&M, and the carbon term are expressed per MWh of
    fuel input. Dividing their sum by thermal efficiency converts them to
    DKK/MWh_th. The electricity term credits the market value of co-produced
    electricity. Only the external heat price is bounded at zero; the raw CHP
    marginal cost is retained for diagnostics.
    """
    if not 0 < eta_th <= 1:
        raise ValueError(f"eta_th must lie in (0, 1], received {eta_th}")
    if not 0 <= eta_el <= 1:
        raise ValueError(f"eta_el must lie in [0, 1], received {eta_el}")

    fuel_related_cost_dkk_per_mwh_input = (
        bio_fuel_dkk_per_mwh_input
        + chp_vom_dkk_per_mwh_input
        + bio_fossil_co2_t_per_mwh_input * co2_price_dkk_per_t
    )

    mc_unbounded = 100 + (
        fuel_related_cost_dkk_per_mwh_input / eta_th
        - p_el_dkk_per_mwh_el * (eta_el / eta_th)
    )
    mc_unbounded.name = "mc_heat_chp_unbounded_dkk_per_mwh_th"

    dynamic_heat_price = mc_unbounded.clip(lower=dynamic_heat_price_floor)
    # Backward-compatible name used by the PyPSA model input routine.
    dynamic_heat_price.name = "mc_heat_chp_dkk_per_mwh_th"
    return mc_unbounded, dynamic_heat_price


def main() -> None:
    snapshots = build_snapshots(year=YEAR, freq=FREQ)

    p_el = load_elspot_prices_hourly(
        csv_path=ELEC_CSV,
        sep=SEP,
        time_col=TIME_COL,
        price_col=PRICE_COL,
        snapshots=snapshots,
    )

    p_veks = build_veks_price_hourly(
        snapshots=snapshots,
        veks_kr_per_gj=VEKS_KR_PER_GJ,
    )

    mc_heat_chp_unbounded, mc_heat_chp = compute_mc_heat_chp(
        p_el_dkk_per_mwh_el=p_el,
        bio_fuel_dkk_per_mwh_input=BIO_FUEL_DKK_PER_MWH_INPUT,
        chp_vom_dkk_per_mwh_input=CHP_VOM_DKK_PER_MWH_INPUT,
        bio_fossil_co2_t_per_mwh_input=BIO_FOSSIL_CO2_T_PER_MWH_INPUT,
        co2_price_dkk_per_t=CO2_PRICE_DKK_PER_T,
        eta_th=ETA_TH,
        eta_el=ETA_EL,
        dynamic_heat_price_floor=DYNAMIC_HEAT_PRICE_FLOOR,
    )

    spread = p_veks - (mc_heat_chp / ETA_RT)
    spread.name = "spread_veks_minus_mc_over_eta_rt"

    out = pd.concat(
        [p_el, p_veks, mc_heat_chp_unbounded, mc_heat_chp, spread],
        axis=1,
    )
    out.to_csv(OUT_CSV, index_label="time")

    intercept = (
        BIO_FUEL_DKK_PER_MWH_INPUT
        + CHP_VOM_DKK_PER_MWH_INPUT
        + BIO_FOSSIL_CO2_T_PER_MWH_INPUT * CO2_PRICE_DKK_PER_T
    ) / ETA_TH
    electricity_coefficient = ETA_EL / ETA_TH

    print(f"Wrote {OUT_CSV}")
    print(
        "Dynamic heat-price equation: "
        f"c_DH(t) = max({DYNAMIC_HEAT_PRICE_FLOOR:.1f}, "
        f"{intercept:.3f} - {electricity_coefficient:.6f} * c_el(t))"
    )
    print(
        "Hours affected by the zero-price floor: "
        f"{int((mc_heat_chp_unbounded < DYNAMIC_HEAT_PRICE_FLOOR).sum())}"
    )
    print(out.head(24))
    print("\nElectricity price summary:\n", p_el.describe())
    print("\nUnbounded CHP marginal heat-cost summary:\n", mc_heat_chp_unbounded.describe())
    print("\nBounded dynamic external heat-price summary:\n", mc_heat_chp.describe())
    print("\nVEKS price summary:\n", p_veks.describe())


if __name__ == "__main__":
    main()
