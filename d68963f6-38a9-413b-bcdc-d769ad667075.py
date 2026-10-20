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

YEAR = 2024
SOLVER_NAME = "gurobi"
PRICE_AREA = "DK2"

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
DEMAND_ADJUSTMENT_SAFETY_MARGIN = 1e-6
PTES_ENERGY_CAPACITY_MWH = 3300

# Heat pump operating assumptions
CITY2_HP = "City 2 heat pump Hoje Taastrup"
GROUNDWATER_HP = "Ground water sourced HP Hoje Taastrup"

CITY2_HEAT_CAPACITY_MW = 1.34
GROUNDWATER_HEAT_CAPACITY_MW = 1.50

# DEA central estimate
HP_MIN_LOAD_PU = 0.25

# DEA 2025 central estimate
HP_START_UP_COST_EUR_PER_MW_TH = 10.63

# Fixed EUR/DKK central parity
EUR_TO_DKK = 7.46038

CITY2_START_UP_COST_DKK = (
    HP_START_UP_COST_EUR_PER_MW_TH
    * CITY2_HEAT_CAPACITY_MW
    * EUR_TO_DKK
)

GROUNDWATER_START_UP_COST_DKK = (
    HP_START_UP_COST_EUR_PER_MW_TH
    * GROUNDWATER_HEAT_CAPACITY_MW
    * EUR_TO_DKK
)

# Provisional anti-short-cycling assumptions
HP_MIN_UP_TIME_H = 2
HP_MIN_DOWN_TIME_H = 2

DISTRICT_HEATING_FILE = DATA_DIR / "HT_PTES_data.xlsx"
ELECTRICITY_PRICE_FILE = DATA_DIR / "Elspotprices.csv"
PTES_DISPATCH_FILE = DATA_DIR / "ptes_operation_data_hourly.csv"
COP_PROFILES_FILE = DATA_DIR / "dh_cop_profiles_hj_taastrup.csv"

MODEL_OUTPUT_PATH = RESULTS_DIR / f"hoje_taastrup_dh_fixed_ptes_{YEAR}.nc"


# --------------------------
# Helpers
# --------------------------
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


def repeat_hourly_profile_for_year(
    data: pd.DataFrame,
    target_year: int,
    name: str,
) -> pd.DataFrame:
    """Map an hourly profile to a target year by month, day, and hour.

    If the target year is a leap year but the source profile is not, the
    28 February profile is copied to 29 February.
    """
    data = data.copy().sort_index()

    if not isinstance(data.index, pd.DatetimeIndex):
        raise TypeError(f"{name} must have a DatetimeIndex.")
    if len(data) not in (8760, 8784):
        raise ValueError(
            f"{name} has {len(data)} rows; expected a complete hourly year."
        )
    if data.index.has_duplicates:
        raise ValueError(f"{name} contains duplicate timestamps.")

    profile = {
        (timestamp.month, timestamp.day, timestamp.hour): row
        for timestamp, row in data.iterrows()
    }
    snapshots = pd.date_range(
        start=f"{target_year}-01-01 00:00:00",
        end=f"{target_year}-12-31 23:00:00",
        freq="h",
    )

    rows = []
    for timestamp in snapshots:
        key = (timestamp.month, timestamp.day, timestamp.hour)
        if key not in profile and timestamp.month == 2 and timestamp.day == 29:
            key = (2, 28, timestamp.hour)
        if key not in profile:
            raise ValueError(
                f"{name} has no value for {timestamp.month:02d}-"
                f"{timestamp.day:02d} {timestamp.hour:02d}:00."
            )
        rows.append(profile[key])

    repeated = pd.DataFrame(rows, index=snapshots)
    repeated.columns = data.columns
    return repeated


def build_monthly_veks_price(snapshots: pd.DatetimeIndex) -> pd.Series:
    """Return the monthly VEKS tariff in DKK/MWh_th."""
    return pd.Series(
        [VEKS_KR_PER_GJ[timestamp.month] * GJ_PER_MWH for timestamp in snapshots],
        index=snapshots,
        name="VEKS price [DKK/MWh_th]",
    )


def load_electricity_prices(
    path: Path,
    year: int,
    price_area: str,
) -> pd.Series:
    df = pd.read_csv(path, sep=";")
    df["HourUTC"] = pd.to_datetime(df["HourUTC"], utc=True)

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
    series.index = series.index.tz_localize(None)
    series.name = "SpotPriceDKK"
    return series


def load_fixed_ptes_dispatch(path: Path, year: int) -> pd.DataFrame:
    """Load and validate the measured hourly PTES operation."""
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()

    required_cols = ["Q_storage_mwh", "E_charge_mwh", "E_discharge_mwh"]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing PTES dispatch columns: {missing}")

    dispatch = df[required_cols].copy()
    dispatch.index = dispatch.index.tz_localize(None)
    dispatch = dispatch[dispatch.index.year == year]

    validate_full_year_length(dispatch, year, "Fixed PTES dispatch")
    if dispatch.index.has_duplicates:
        raise ValueError("Fixed PTES dispatch contains duplicate timestamps.")
    if not dispatch.index.equals(
        pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00:00", freq="h")
    ):
        raise ValueError("Fixed PTES dispatch is not a continuous hourly profile.")

    dispatch = dispatch.rename(
        columns={
            "E_charge_mwh": "ptes_charge_mw",
            "E_discharge_mwh": "ptes_discharge_mw",
        }
    )

    return dispatch


# --------------------------
# Load data
# --------------------------
district_heating_data = pd.read_excel(DISTRICT_HEATING_FILE)
district_heating_data = district_heating_data.rename(columns={"Unnamed: 0": "time"})
district_heating_data["time"] = pd.to_datetime(district_heating_data["time"])
district_heating_data = district_heating_data.set_index("time").sort_index()
district_heating_data = repeat_hourly_profile_for_year(
    district_heating_data,
    YEAR,
    "District heating data",
)

electricity_price = load_electricity_prices(
    ELECTRICITY_PRICE_FILE,
    YEAR,
    PRICE_AREA,
)

ptes_dispatch = load_fixed_ptes_dispatch(
    PTES_DISPATCH_FILE,
    YEAR,
)

heat_pumps_cop_profiles = pd.read_csv(
    COP_PROFILES_FILE,
    index_col=0,
    parse_dates=True,
).sort_index()
heat_pumps_cop_profiles = repeat_hourly_profile_for_year(
    heat_pumps_cop_profiles,
    YEAR,
    "Heat pump COP profiles",
)


# --------------------------
# Build network
# --------------------------
n = pypsa.Network()
n.set_snapshots(district_heating_data.index)

veks_price = build_monthly_veks_price(n.snapshots)

price = align_to_snapshots(
    electricity_price,
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

cop_gw = align_to_snapshots(
    heat_pumps_cop_profiles["GW_HP"],
    n.snapshots,
)

cop_city2 = align_to_snapshots(
    heat_pumps_cop_profiles["CITY2_HP"],
    n.snapshots,
)

unscaled_heat_demand = align_to_snapshots(
    district_heating_data["HT DH Demand (MW)"],
    n.snapshots,
)
if unscaled_heat_demand.isna().any() or (unscaled_heat_demand <= 0).any():
    raise ValueError("Heat demand must contain positive values for every snapshot.")

heat_demand = unscaled_heat_demand.copy()
adjusted_demand_hours = ptes_discharge > heat_demand
heat_demand.loc[adjusted_demand_hours] = (
    ptes_discharge.loc[adjusted_demand_hours]
    * (1.0 + DEMAND_ADJUSTMENT_SAFETY_MARGIN)
)

print(f"Adjusted demand hours: {adjusted_demand_hours.sum()}")
print(
    "Additional annual demand from adjustment: "
    f"{(heat_demand - unscaled_heat_demand).sum():.3f} MWh"
)
print(
    "Minimum demand minus fixed PTES discharge: "
    f"{(heat_demand - ptes_discharge).min():.6f} MW"
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
    p_nom=float(heat_demand.max() + ptes_charge.max()),
    marginal_cost=veks_price,
    carrier="Main DH system",
)

n.add(
    "Link",
    "HX Hoje Taastrup",
    bus0="DH CPH",
    bus1="DH Hoje Taastrup",
    efficiency=1.0,
    p_nom=float(heat_demand.max()),
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
    CITY2_HP,
    bus0="electricity market",
    bus1="cooling source",
    bus2="DH Hoje Taastrup",
    efficiency=-(cop_city2 - 1.0),
    efficiency2=cop_city2,
    p_nom=CITY2_HEAT_CAPACITY_MW / float(cop_city2.mean()),
    p_min_pu=HP_MIN_LOAD_PU,
    committable=True,
    start_up_cost=CITY2_START_UP_COST_DKK,
    min_up_time=HP_MIN_UP_TIME_H,
    min_down_time=HP_MIN_DOWN_TIME_H,
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
    GROUNDWATER_HP,
    bus0="electricity market",
    bus1="Ground water source",
    bus2="DH Hoje Taastrup",
    efficiency=-(cop_gw - 1.0),
    efficiency2=cop_gw,
    p_nom=GROUNDWATER_HEAT_CAPACITY_MW / float(cop_gw.mean()),
    p_min_pu=HP_MIN_LOAD_PU,
    committable=True,
    start_up_cost=GROUNDWATER_START_UP_COST_DKK,
    min_up_time=HP_MIN_UP_TIME_H,
    min_down_time=HP_MIN_DOWN_TIME_H,
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
    p_nom=float(ptes_charge.max()),
    p_set=ptes_charge,
    efficiency=1.0,
    carrier="PTES",
)

n.add(
    "Link",
    "Hoje Taastrup PTES discharger",
    bus0="Hoje Taastrup PTES",
    bus1="DH Hoje Taastrup",
    p_nom=float(ptes_discharge.max()),
    p_set=ptes_discharge,
    efficiency=1.0,
    carrier="PTES",
)

n.add(
    "Store",
    "Hoje Taastrup PTES storage",
    bus="Hoje Taastrup PTES",
    e_nom=PTES_ENERGY_CAPACITY_MWH,
    e_initial=float(ptes_dispatch["Q_storage_mwh"].iloc[0]),
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
    p_set=heat_demand,
    carrier="Hoje Taastrup system",
)


# --------------------------
# Optimize and export
# --------------------------
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

status, condition = n.optimize(solver_name=SOLVER_NAME)
if condition != "optimal":
    raise RuntimeError(
        f"Optimization failed: status={status}, condition={condition}"
    )

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
print(
    "Equivalent full PTES cycles:",
    ptes_discharge.sum() / PTES_ENERGY_CAPACITY_MWH,
)

print(f"Saved optimized network to: {MODEL_OUTPUT_PATH}")
