#!/usr/bin/env python3
from pathlib import Path

import pandas as pd
import pypsa
import xarray as xr


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
# Layer 3a PTES operating assumptions
# --------------------------
# Values are derived from the gradient note:
# - PTES charge/discharge capacity: 30 MW
# - PTES ramp rate: 0.2 MW/min = 12 MW/h
# - Minimum warm-keeping flow through the aggregate HX connection: 0.5 MW
# - No reversal between charging and discharging for 2 hours
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
PTES_MIN_CHARGE_MW = 10.0
PTES_MIN_DISCHARGE_MW = 5.0
PTES_RAMP_LIMIT_MW_PER_H = 12.0
HX_HOJE_TAASTRUP_CAPACITY_MW = 100.0  # Assumed aggregate capacity; not specified in the gradient note.
MIN_HX_FLOW_MW = 0.5
PTES_PHASE_SHIFT_HOURS = 2

DISTRICT_HEATING_FILE = DATA_DIR / "HT_PTES_data.xlsx"
PRICE_SIGNALS_FILE = DATA_DIR / f"veks_and_mc_heat_chp_{YEAR}_hourly.csv"
ELECTRICITY_PRICE_FILE = DATA_DIR / "Elspotprices.csv"
COP_PROFILES_FILE = DATA_DIR / "dh_cop_profiles_hj_taastrup.csv"

MODEL_OUTPUT_PATH = RESULTS_DIR / f"hoje_taastrup_dh_optimized_{YEAR}_layer3a_no_reversal.nc"

# --------------------------
# Heat pump operating assumptions
# --------------------------
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


def align_to_snapshots(series: pd.Series, snapshots: pd.DatetimeIndex) -> pd.Series:
    """
    Align a series to the network snapshots and fill small gaps if needed.
    """
    return series.reindex(snapshots).ffill().bfill()



def add_ptes_layer3a_constraints(n: pypsa.Network, snapshots: pd.DatetimeIndex) -> None:
    """
    Add Layer 3a PTES operating constraints.

    This includes all Layer 1 and Layer 2 constraints plus a 2-hour no-reversal rule.

    Layer 1 constraints:
    1. PTES charge ramp limit: +/- 12 MW/h
    2. PTES discharge ramp limit: +/- 12 MW/h
    3. PTES discharge cannot exceed local Høje Taastrup heat demand

    Layer 2 constraints:
    4. Binary charging status variable
    5. Binary discharging status variable
    6. If charging is active, charge power must be between 10 and 30 MW
    7. If discharging is active, discharge power must be between 5 and 30 MW
    8. PTES cannot charge and discharge in the same snapshot

    Layer 3a constraint:
    9. If the PTES is charging in snapshot t, it cannot discharge in
       snapshots t+1 or t+2. The same rule is applied in the opposite
       direction from discharging to charging.

    Notes:
    - The model is a MILP because of the binary variables.
    - The 12-hour full-charge to full-discharge restriction is not included.
    """
    m = n.model
    p_link = m.variables["Link-p"]

    charger = p_link.sel(name=PTES_CHARGER)
    discharger = p_link.sel(name=PTES_DISCHARGER)

    # --------------------------
    # Binary operating-mode variables
    # --------------------------
    y_charge = m.add_variables(
        coords=[snapshots],
        binary=True,
        name="ptes_charge_status",
    )
    y_discharge = m.add_variables(
        coords=[snapshots],
        binary=True,
        name="ptes_discharge_status",
    )

    # --------------------------
    # PTES ramp-rate constraints
    # --------------------------
    # The gradient note gives 0.2 MW/min, i.e. 12 MW/h.
    # Since the model is hourly, this limits changes between consecutive
    # hourly snapshots to +/- 12 MW.
    charger_diff = charger.diff("snapshot")
    discharger_diff = discharger.diff("snapshot")

    m.add_constraints(
        charger_diff <= PTES_RAMP_LIMIT_MW_PER_H,
        name="ptes_charger_ramp_up",
    )
    m.add_constraints(
        charger_diff >= -PTES_RAMP_LIMIT_MW_PER_H,
        name="ptes_charger_ramp_down",
    )

    m.add_constraints(
        discharger_diff <= PTES_RAMP_LIMIT_MW_PER_H,
        name="ptes_discharger_ramp_up",
    )
    m.add_constraints(
        discharger_diff >= -PTES_RAMP_LIMIT_MW_PER_H,
        name="ptes_discharger_ramp_down",
    )

    # --------------------------
    # Discharge absorption limit
    # --------------------------
    # The gradient note states that maximum discharge is limited by what can
    # actually be absorbed in the HTF distribution network. In this aggregate
    # version, this is approximated by the local heat demand.
    heat_demand = n.loads_t.p_set[DH_LOAD].reindex(snapshots)

    heat_demand_da = xr.DataArray(
        heat_demand.to_numpy(),
        coords={"snapshot": snapshots},
        dims=("snapshot",),
    )

    m.add_constraints(
        discharger <= heat_demand_da,
        name="ptes_discharge_limited_by_heat_demand",
    )

    # --------------------------
    # Minimum active power and mutually exclusive modes
    # --------------------------
    # Charging mode:
    # y_charge = 0 -> charger = 0
    # y_charge = 1 -> 10 MW <= charger <= 30 MW
    m.add_constraints(
        charger >= PTES_MIN_CHARGE_MW * y_charge,
        name="ptes_min_charge_when_active",
    )
    m.add_constraints(
        charger <= PTES_POWER_CAPACITY_MW * y_charge,
        name="ptes_max_charge_when_active",
    )

    # Discharging mode:
    # y_discharge = 0 -> discharger = 0
    # y_discharge = 1 -> 5 MW <= discharger <= 30 MW
    m.add_constraints(
        discharger >= PTES_MIN_DISCHARGE_MW * y_discharge,
        name="ptes_min_discharge_when_active",
    )
    m.add_constraints(
        discharger <= PTES_POWER_CAPACITY_MW * y_discharge,
        name="ptes_max_discharge_when_active",
    )

    # The PTES can charge, discharge, or idle, but not charge and discharge
    # at the same time.
    m.add_constraints(
        y_charge + y_discharge <= 1,
        name="ptes_no_simultaneous_charge_discharge",
    )

    # --------------------------
    # 2-hour no-reversal / phase-shift constraint
    # --------------------------
    # The gradient note states that a phase shift takes 2 hours.
    # With hourly snapshots, this is approximated as:
    # - if charging at t, discharging is forbidden at t+1 and t+2
    # - if discharging at t, charging is forbidden at t+1 and t+2
    #
    # The future variables are assigned the current snapshot coordinates so
    # Linopy adds pairwise constraints y_t + y_{t+k} <= 1 rather than aligning
    # by timestamp labels.
    for k in range(1, PTES_PHASE_SHIFT_HOURS + 1):
        current_snapshots = snapshots[:-k]
        future_snapshots = snapshots[k:]

        y_charge_now = y_charge.sel(snapshot=current_snapshots)
        y_discharge_now = y_discharge.sel(snapshot=current_snapshots)

        y_charge_future = y_charge.sel(snapshot=future_snapshots).assign_coords(
            snapshot=current_snapshots
        )
        y_discharge_future = y_discharge.sel(snapshot=future_snapshots).assign_coords(
            snapshot=current_snapshots
        )

        m.add_constraints(
            y_charge_now + y_discharge_future <= 1,
            name=f"ptes_no_charge_to_discharge_within_{k}h",
        )
        m.add_constraints(
            y_discharge_now + y_charge_future <= 1,
            name=f"ptes_no_discharge_to_charge_within_{k}h",
        )


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
district_heating_data = repeat_hourly_profile_for_year(
    district_heating_data,
    YEAR,
    "District heating data",
)

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
    CITY2_HP,
    bus0="electricity market",
    bus1="cooling source",
    bus2="DH Hoje Taastrup",
    efficiency=-(cop_city2 - 1.0),
    efficiency2=cop_city2,

    # Fixed electrical capacity based on the mean COP
    p_nom=CITY2_HEAT_CAPACITY_MW / float(cop_city2.mean()),

    # DEA minimum load: 25% of the available full load
    p_min_pu=HP_MIN_LOAD_PU,

    # Unit-commitment parameters
    committable=True,
    start_up_cost=CITY2_START_UP_COST_DKK,
    min_up_time=HP_MIN_UP_TIME_H,
    min_down_time=HP_MIN_DOWN_TIME_H,

    carrier="Hoje Taastrup system",
)
# --------------------------
# Groundwater-sourced heat pump
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

    # Fixed electrical capacity based on the mean COP
    p_nom=GROUNDWATER_HEAT_CAPACITY_MW / float(cop_gw.mean()),

    # DEA minimum load: 25% of the available full load
    p_min_pu=HP_MIN_LOAD_PU,

    # Unit-commitment parameters
    committable=True,
    start_up_cost=GROUNDWATER_START_UP_COST_DKK,
    min_up_time=HP_MIN_UP_TIME_H,
    min_down_time=HP_MIN_DOWN_TIME_H,

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

n.optimize(
    solver_name=SOLVER_NAME,
    extra_functionality=add_ptes_layer3a_constraints,
)
n.export_to_netcdf(MODEL_OUTPUT_PATH)

print(f"Saved optimized network to: {MODEL_OUTPUT_PATH}")


charger = n.links_t.p0["Hoje Taastrup PTES charger"]
discharger = n.links_t.p0["Hoje Taastrup PTES discharger"]

is_charging = charger > 1e-4
is_discharging = discharger > 1e-4

for k in [1, 2]:
    charge_to_discharge = (is_charging.iloc[:-k].to_numpy() & is_discharging.iloc[k:].to_numpy()).sum()
    discharge_to_charge = (is_discharging.iloc[:-k].to_numpy() & is_charging.iloc[k:].to_numpy()).sum()

    print(f"Charge to discharge within {k}h:", charge_to_discharge)
    print(f"Discharge to charge within {k}h:", discharge_to_charge)
