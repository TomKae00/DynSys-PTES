#!/usr/bin/env python3
from pathlib import Path

import pandas as pd
import pypsa


# --------------------------
# Settings
# --------------------------
DATA_DIR = Path("Data")
RESULTS_DIR = Path("results")

YEAR = 2024
FREQ = "h"
SOLVER_NAME = "gurobi"
PRICE_AREA = "DK2"

# --------------------------
# Layer 1 PTES operating assumptions
# --------------------------
# Values are derived from the gradient note:
# - PTES charge/discharge capacity: 30 MW
# - Minimum warm-keeping flow through the aggregate HX connection: 0.5 MW
#
# The current model represents Høje Taastrup as one aggregate heat bus.
# Therefore, the Lervangen warm-keeping flow is approximated as a minimum
# flow through the aggregate "HX Hoje Taastrup" link.
PTES_CHARGER = "Hoje Taastrup PTES charger"
PTES_DISCHARGER = "Hoje Taastrup PTES discharger"
PTES_STORAGE = "Hoje Taastrup PTES storage"
DH_LOAD = "Hoje Taastrup DH load"
HX_HOJE_TAASTRUP = "HX Hoje Taastrup"

PTES_POWER_CAPACITY_MW = 30.0
HX_HOJE_TAASTRUP_CAPACITY_MW = 100.0  # Assumed aggregate capacity; not specified in the gradient note.
MIN_HX_FLOW_MW = 0.5

DISTRICT_HEATING_FILE = DATA_DIR / "HT_PTES_data.xlsx"
PRICE_SIGNALS_FILE = DATA_DIR / f"veks_and_mc_heat_chp_{YEAR}_hourly.csv"
ELECTRICITY_PRICE_FILE = DATA_DIR / "Elspotprices.csv"
COP_PROFILES_FILE = DATA_DIR / "dh_cop_profiles_hj_taastrup.csv"

MODEL_OUTPUT_PATH = RESULTS_DIR / f"hoje_taastrup_dh_optimized_{YEAR}.nc"


# --------------------------
# Helpers
# --------------------------
def reset_index_to_year(
    data: pd.DataFrame | pd.Series,
    year: int,
    freq: str = "h",
) -> pd.DataFrame | pd.Series:
    """
    Replace the existing datetime index with a fresh hourly index for the
    selected year, keeping the same number of rows.
    """
    data = data.copy()
    new_index = pd.date_range(
        start=f"{year}-01-01 00:00:00",
        periods=len(data),
        freq=freq,
    )
    data.index = new_index
    return data


def expected_hours_in_year(year: int) -> int:
    """
    Return the expected number of hourly snapshots for the selected year.
    """
    return 8784 if pd.Timestamp(f"{year}-01-01").is_leap_year else 8760


def add_leap_day_from_feb_28(
    data: pd.DataFrame | pd.Series,
    year: int,
) -> pd.DataFrame | pd.Series:
    """
    Extend a 8760-hour profile to a leap year by using the 24 values from
    28 February also for 29 February.
    """
    if expected_hours_in_year(year) == 8784 and len(data) == 8760:
        feb_29_position = (31 + 28) * 24
        feb_28 = data.iloc[feb_29_position - 24:feb_29_position].copy()
        data = pd.concat(
            [
                data.iloc[:feb_29_position],
                feb_28,
                data.iloc[feb_29_position:],
            ]
        )

    return data


def validate_full_year_length(
    data: pd.DataFrame | pd.Series,
    year: int,
    name: str,
) -> None:
    """
    Check that the data length matches the selected model year.
    """
    expected = expected_hours_in_year(year)
    actual = len(data)

    if actual != expected:
        raise ValueError(
            f"{name} has {actual} rows, but year {year} requires {expected} hourly values."
        )


def align_to_snapshots(series: pd.Series, snapshots: pd.DatetimeIndex) -> pd.Series:
    """
    Align a series to the network snapshots and fill small gaps if needed.
    """
    return series.reindex(snapshots).ffill().bfill()


def load_electricity_prices(
    path: Path,
    year: int,
    price_area: str,
) -> pd.Series:
    """
    Load electricity prices from Elspotprices.csv, filter by price area and year,
    and return SpotPriceDKK as a numeric hourly series indexed by HourUTC.
    """
    df = pd.read_csv(path, sep=";")
    df["HourUTC"] = pd.to_datetime(df["HourUTC"])

    df = df[df["PriceArea"] == price_area].copy()
    df = df.sort_values("HourUTC")

    prices = df["SpotPriceDKK"].astype(str).str.replace(",", ".", regex=False)
    df["SpotPriceDKK"] = pd.to_numeric(prices, errors="coerce")

    df = df.set_index("HourUTC")
    df = df[df.index.year == year].copy()

    expected = expected_hours_in_year(year)
    actual = len(df)

    if actual != expected:
        raise ValueError(
            f"Electricity price data for {price_area} in year {year} has {actual} rows, "
            f"but expected {expected}."
        )

    if df.index.has_duplicates:
        raise ValueError(
            f"Electricity price data for {price_area} in year {year} contains duplicate timestamps."
        )

    series = df["SpotPriceDKK"].copy()
    series.name = "SpotPriceDKK"
    return series


# --------------------------
# Load data
# --------------------------
# District heating demand
district_heating_data = pd.read_excel(DISTRICT_HEATING_FILE)
district_heating_data = district_heating_data.rename(columns={"Unnamed: 0": "time"})
district_heating_data["time"] = pd.to_datetime(district_heating_data["time"])
district_heating_data = district_heating_data.set_index("time").sort_index()
district_heating_data = add_leap_day_from_feb_28(district_heating_data, YEAR)
validate_full_year_length(district_heating_data, YEAR, "District heating data")
district_heating_data = reset_index_to_year(district_heating_data, YEAR, FREQ)

# Precomputed price signals
price_signals = pd.read_csv(
    PRICE_SIGNALS_FILE,
    index_col="time",
    parse_dates=True,
).sort_index()
validate_full_year_length(price_signals, YEAR, "Price signals")
price_signals = reset_index_to_year(price_signals, YEAR, FREQ)

# Electricity prices: use real timestamps from file, filter by year and price area
electricity_price = load_electricity_prices(
    ELECTRICITY_PRICE_FILE,
    YEAR,
    PRICE_AREA,
)

# COP profiles
heat_pumps_cop_profiles = pd.read_csv(
    COP_PROFILES_FILE,
    index_col=0,
    parse_dates=True,
).sort_index()
heat_pumps_cop_profiles = add_leap_day_from_feb_28(heat_pumps_cop_profiles, YEAR)
validate_full_year_length(heat_pumps_cop_profiles, YEAR, "Heat pump COP profiles")
heat_pumps_cop_profiles = reset_index_to_year(heat_pumps_cop_profiles, YEAR, FREQ)


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
    p_nom_extendable=True,
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
    p_nom=100,
    marginal_cost=mc_heat_chp,
    carrier="Main DH system",
)

n.add(
    "Link",
    HX_HOJE_TAASTRUP,
    bus0="DH CPH",
    bus1="DH Hoje Taastrup",
    efficiency=1.0,
    p_nom=HX_HOJE_TAASTRUP_CAPACITY_MW,
    p_min_pu=MIN_HX_FLOW_MW / HX_HOJE_TAASTRUP_CAPACITY_MW,
    carrier="Main DH system",
)


# --------------------------
# Geothermal / City2 heat pump
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
    "City 2 heat pump Hoje Taastrup",
    bus0="electricity market",
    bus1="cooling source",
    bus2="DH Hoje Taastrup",
    efficiency=-(cop_city2 - 1.0),
    efficiency2=cop_city2,
    p_nom=1.3 / cop_city2,
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
    efficiency=-(cop_gw - 1.0), #3.4
    efficiency2=cop_gw, #3.4
    p_nom=1.5 / 3.4,
    carrier="Hoje Taastrup system",
)


# --------------------------
# Hoje Taastrup PTES
# --------------------------
n.add(
    "Link",
    PTES_CHARGER,
    bus0="DH CPH",
    bus1="Hoje Taastrup PTES",
    p_nom=PTES_POWER_CAPACITY_MW,
    efficiency=1.0,
    carrier="PTES",
)

n.add(
    "Link",
    PTES_DISCHARGER,
    bus0="Hoje Taastrup PTES",
    bus1="DH Hoje Taastrup",
    p_nom=PTES_POWER_CAPACITY_MW,
    efficiency=1.0,
    carrier="PTES",
)

n.add(
    "Store",
    PTES_STORAGE,
    bus="Hoje Taastrup PTES",
    e_nom=3300,
    e_initial=1500,
    standing_loss=0.002,
    carrier="PTES",
)


# --------------------------
# District heating demand
# --------------------------
n.add(
    "Load",
    DH_LOAD,
    bus="DH Hoje Taastrup",
    p_set=district_heating_data["HT DH Demand (MW)"],
    carrier="Hoje Taastrup system",
)


# --------------------------
# Optimize and export
# --------------------------
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

n.optimize(solver_name=SOLVER_NAME)
n.export_to_netcdf(MODEL_OUTPUT_PATH)

print(f"Saved optimized network to: {MODEL_OUTPUT_PATH}")
