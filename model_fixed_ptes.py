#!/usr/bin/env python3
from pathlib import Path

import pandas as pd
import pypsa

import matplotlib.pyplot as plt


# --------------------------
# Settings
# --------------------------
DATA_DIR = Path("Data")
RESULTS_DIR = Path("results")

YEAR = 2023
FREQ = "h"
SOLVER_NAME = "gurobi"
PRICE_AREA = "DK2"

DISTRICT_HEATING_FILE = DATA_DIR / "HT_PTES_data.xlsx"
PRICE_SIGNALS_FILE = DATA_DIR / f"veks_and_mc_heat_chp_{YEAR}_hourly.csv"
ELECTRICITY_PRICE_FILE = DATA_DIR / "Elspotprices.csv"
COP_PROFILES_FILE = DATA_DIR / "dh_cop_profiles_hj_taastrup.csv"
PTES_DISPATCH_FILE = DATA_DIR / "ptes_operation_data_hourly.csv"

MODEL_OUTPUT_PATH = RESULTS_DIR / f"hoje_taastrup_dh_fixed_ptes_{YEAR}.nc"


# --------------------------
# Helpers
# --------------------------
def reset_index_to_year(
    data: pd.DataFrame | pd.Series,
    year: int,
    freq: str = "h",
) -> pd.DataFrame | pd.Series:
    data = data.copy()
    data.index = pd.date_range(
        start=f"{year}-01-01 00:00:00",
        periods=len(data),
        freq=freq,
    )
    return data


def expected_hours_in_year(year: int) -> int:
    return 8784 if pd.Timestamp(f"{year}-01-01").is_leap_year else 8760


def validate_full_year_length(
    data: pd.DataFrame | pd.Series,
    year: int,
    name: str,
) -> None:
    expected = expected_hours_in_year(year)
    actual = len(data)

    if actual != expected:
        raise ValueError(
            f"{name} has {actual} rows, but year {year} requires {expected} hourly values."
        )


def align_to_snapshots(series: pd.Series, snapshots: pd.DatetimeIndex) -> pd.Series:
    return series.reindex(snapshots).ffill().bfill()


def load_electricity_prices(
    path: Path,
    year: int,
    price_area: str,
) -> pd.Series:
    df = pd.read_csv(path, sep=";")
    df["HourUTC"] = pd.to_datetime(df["HourUTC"])

    df = df[df["PriceArea"] == price_area].copy()
    df = df.sort_values("HourUTC")

    df["SpotPriceDKK"] = pd.to_numeric(
        df["SpotPriceDKK"].astype(str).str.replace(",", ".", regex=False),
        errors="coerce",
    )

    df = df.set_index("HourUTC")
    df = df[df.index.year == year].copy()

    expected = expected_hours_in_year(year)
    actual = len(df)

    if actual != expected:
        raise ValueError(
            f"Electricity price data for {price_area} in {year} has {actual} rows, "
            f"but expected {expected}."
        )

    if df.index.has_duplicates:
        raise ValueError(
            f"Electricity price data for {price_area} in {year} contains duplicate timestamps."
        )

    series = df["SpotPriceDKK"].copy()
    series.name = "SpotPriceDKK"
    return series


def load_fixed_ptes_dispatch(path: Path, target_year: int) -> pd.DataFrame:
    """
    Load 2024 PTES 10-minute data, convert to hourly fixed link dispatch,
    drop Feb 29, and reset index to the chosen non-leap target year.

    Assumption:
    E_charge and E_discharge are energy values per 10-minute interval.
    Therefore hourly MW values are obtained by summing within each hour.
    """
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()

    required_cols = ["E_charge_mwh", "E_discharge_mwh"]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing PTES dispatch columns: {missing}")

    dispatch = df[required_cols].copy()

    # Convert 10-minute energy values to hourly average MW by hourly summation
    dispatch_hourly = dispatch.resample("h").sum()

    # Drop leap day to go from 8784 -> 8760 hours
    dispatch_hourly = dispatch_hourly[
        ~((dispatch_hourly.index.month == 2) & (dispatch_hourly.index.day == 29))
    ]

    # Remove timezone to match other data
    dispatch_hourly.index = dispatch_hourly.index.tz_localize(None)

    validate_full_year_length(dispatch_hourly, target_year, "Fixed PTES dispatch")

    dispatch_hourly = reset_index_to_year(dispatch_hourly, target_year, "h")
    dispatch_hourly = dispatch_hourly.rename(
        columns={
            "E_charge_mwh": "ptes_charge_mw",
            "E_discharge_mwh": "ptes_discharge_mw",
        }
    )

    return dispatch_hourly


# --------------------------
# Load data
# --------------------------
district_heating_data = pd.read_excel(DISTRICT_HEATING_FILE)
district_heating_data = district_heating_data.rename(columns={"Unnamed: 0": "time"})
district_heating_data["time"] = pd.to_datetime(district_heating_data["time"])
district_heating_data = district_heating_data.set_index("time").sort_index()
validate_full_year_length(district_heating_data, YEAR, "District heating data")
district_heating_data = reset_index_to_year(district_heating_data, YEAR, FREQ)

price_signals = pd.read_csv(
    PRICE_SIGNALS_FILE,
    index_col="time",
    parse_dates=True,
).sort_index()
validate_full_year_length(price_signals, YEAR, "Price signals")
price_signals = reset_index_to_year(price_signals, YEAR, FREQ)

electricity_price = load_electricity_prices(
    ELECTRICITY_PRICE_FILE,
    YEAR,
    PRICE_AREA,
)

heat_pumps_cop_profiles = pd.read_csv(
    COP_PROFILES_FILE,
    index_col=0,
    parse_dates=True,
).sort_index()
validate_full_year_length(heat_pumps_cop_profiles, YEAR, "Heat pump COP profiles")
heat_pumps_cop_profiles = reset_index_to_year(heat_pumps_cop_profiles, YEAR, FREQ)

ptes_dispatch = load_fixed_ptes_dispatch(
    PTES_DISPATCH_FILE,
    YEAR,
)


# --------------------------
# Build network
# --------------------------
n = pypsa.Network()
n.set_snapshots(district_heating_data.index)

mc_heat_chp = align_to_snapshots(
    price_signals["mc_heat_chp_dkk_per_mwh_th"],
    n.snapshots,
)

price = align_to_snapshots(
    electricity_price,
    n.snapshots,
)

cop_gw = align_to_snapshots(
    heat_pumps_cop_profiles["GW_HP"],
    n.snapshots,
)

cop_soil = align_to_snapshots(
    heat_pumps_cop_profiles["SOIL_HP"],
    n.snapshots,
)

cop_city2 = align_to_snapshots(
    heat_pumps_cop_profiles["CITY2_HP"],
    n.snapshots,
)

ptes_charge = align_to_snapshots(
    ptes_dispatch["ptes_charge_mw"],
    n.snapshots,
)

ptes_discharge = align_to_snapshots(
    ptes_dispatch["ptes_discharge_mw"],
    n.snapshots,
)


# --------------------------
# Define carriers
# --------------------------
carrier_colors = {
    "heat": ("Heat", "#d62728"),
    "electricity": ("Electricity", "#1f77b4"),
    "heat_source": ("Heat source", "#ff7f0e"),
    "Main DH system": ("Main DH system", "#9467bd"),
    "Hoje Taastrup system": ("Hoje Taastrup system", "#2ca02c"),
    "PTES": ("PTES", "#8c564b"),
    "Electricity market": ("Electricity market", "#7f7f7f"),
    "Geothermal source": ("Geothermal source", "#e377c2"),
    "Groundwater source": ("Groundwater source", "#bcbd22"),
}

for carrier, (nice_name, color) in carrier_colors.items():
    n.add("Carrier", carrier, nice_name=nice_name)
    n.carriers.loc[carrier, "color"] = color


# --------------------------
# Buses
# --------------------------
n.add("Bus", "DH CPH", unit="MW_th", carrier="heat")
n.add("Bus", "DH Hoje Taastrup", unit="MW_th", carrier="heat")
n.add("Bus", "Hoje Taastrup PTES", unit="MW_th", carrier="heat")

n.add("Bus", "electricity market", unit="MW_el", carrier="electricity")

n.add("Bus", "cooling source", unit="MW_th", carrier="heat_source")
n.add("Bus", "Ground water source", unit="MW_th", carrier="heat_source")


# --------------------------
# Electricity market
# --------------------------
n.add(
    "Generator",
    "electricity market",
    bus="electricity market",
    p_nom=100,
#    p_nom_extendable=True,
    marginal_cost=price,
    carrier="Electricity market",
)


# --------------------------
# Main district heating system
# --------------------------
n.add(
    "Generator",
    "DH CPH",
    bus="DH CPH",
#    p_nom=100,
    p_nom_extendable=True,
    marginal_cost=mc_heat_chp,
    carrier="Main DH system",
)

n.add(
    "Link",
    "HX Hoje Taastrup",
    bus0="DH CPH",
    bus1="DH Hoje Taastrup",
    efficiency=1.0,
#    p_nom=100,
    p_nom_extendable=True,
    carrier="Main DH system",
)


# --------------------------
# Geothermal / City2 heat pumpmarg_cost
# --------------------------
n.add(
    "Generator",
    "cooling source",
    bus="cooling source",
    p_nom_extendable=True,
    carrier="Geothermal source",
)

n.add(
    "Link",
    "Geothermal HP Hoje Taastrup",
    bus0="electricity market",
    bus1="cooling source",
    bus2="DH Hoje Taastrup",
    efficiency=-(3.5 - 1.0),
    efficiency2=3.5,
    p_nom=1.3 / 3.5,
    carrier="Hoje Taastrup system",
)


# --------------------------
# Ground water sourced heat pump
# --------------------------
n.add(
    "Generator",
    "Ground water source",
    bus="Ground water source",
    p_nom_extendable=True,
    carrier="Groundwater source",
)

n.add(
    "Link",
    "Ground water sourced HP Hoje Taastrup",
    bus0="electricity market",
    bus1="Ground water source",
    bus2="DH Hoje Taastrup",
    efficiency=-(3.4 - 1.0),
    efficiency2=3.4,
    p_nom=1.5 / 3.4,
    carrier="Hoje Taastrup system",
)


# --------------------------
# Fixed PTES operation via p_set
# --------------------------
n.add(
    "Link",
    "Hoje Taastrup PTES charger",
    bus0="DH CPH",
    bus1="Hoje Taastrup PTES",
    p_nom_extendable=True,
#    p_nom=ptes_charge,
    p_set=ptes_charge,
    efficiency=1.0,
    carrier="PTES",
)

n.add(
    "Link",
    "Hoje Taastrup PTES discharger",
    bus0="Hoje Taastrup PTES",
    bus1="DH Hoje Taastrup",
#   p_nom=ptes_discharge,
    p_nom_extendable=True,
    p_set=ptes_discharge,
    efficiency=1.0,
    carrier="PTES",
)

n.add(
    "Store",
    "Hoje Taastrup PTES storage",
    bus="Hoje Taastrup PTES",
#    e_nom=3300,
    e_initial=1500,
    e_nom_extendable=True,
#    standing_loss=0.002,
    carrier="PTES",
)


# --------------------------
# District heating demand
# --------------------------
n.add(
    "Load",
    "Hoje Taastrup DH load",
    bus="DH Hoje Taastrup",
    p_set=district_heating_data["HT DH Demand (MW)"]*1.5,
    carrier="Hoje Taastrup system",
)


# --------------------------
# Optimize and export
# --------------------------
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

n.optimize(solver_name=SOLVER_NAME)
n.export_to_netcdf(MODEL_OUTPUT_PATH)


fig, ax = plt.subplots(figsize=(12, 5))

ptes_charge.plot(ax=ax, label="PTES charge")
ptes_discharge.plot(ax=ax, label="PTES discharge")

ax.set_title("PTES charge and discharge")
ax.set_xlabel("Time")
ax.set_ylabel("MW")
ax.legend()

plt.tight_layout()
plt.show()

soc_like = (ptes_charge - ptes_discharge).cumsum()

fig, ax = plt.subplots(figsize=(12, 5))
soc_like.plot(ax=ax, label="Cumulative charge - discharge")

ax.set_title("PTES cumulative net balance")
ax.set_xlabel("Time")
ax.set_ylabel("MWh-like balance")
ax.legend()

plt.tight_layout()
plt.show()

print("Annual charge:", ptes_charge.sum())
print("Annual discharge:", ptes_discharge.sum())
print("Net charge - discharge:", ptes_charge.sum() - ptes_discharge.sum())

print(f"Saved optimized network to: {MODEL_OUTPUT_PATH}")