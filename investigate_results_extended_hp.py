#!/usr/bin/env python3
import os
import numpy as np
import pypsa
import pandas as pd
import matplotlib.pyplot as plt

# --------------------------
# Settings
# --------------------------
NET_PATH = "results/hoje_taastrup_dh_optimized_2024_layer3a_no_reversal.nc"
PLOT_DIR = "results/plots_constraints"
DPI = 300
EPS = 1e-4

HEAT_PUMPS = {
    "City2": {
        "link": "City 2 heat pump Hoje Taastrup",
        "thermal_capacity_mw": 1.34,
    },
    "Groundwater": {
        "link": "Ground water sourced HP Hoje Taastrup",
        "thermal_capacity_mw": 1.50,
    },
}

os.makedirs(PLOT_DIR, exist_ok=True)

# --------------------------
# Load network
# --------------------------
n = pypsa.Network(NET_PATH)

# --------------------------
# Helper for saving figures
# --------------------------
def save_fig(filename: str):
    out = os.path.join(PLOT_DIR, filename)
    plt.tight_layout()
    plt.savefig(out, dpi=DPI, bbox_inches="tight")
    plt.close()
    print(f"Saved: {out}")


def get_link_series(attribute: str, link_name: str, default=0.0) -> pd.Series:
    """Return a Link time series, also for older result files without MILP data."""
    table = getattr(n.links_t, attribute, None)
    if isinstance(table, pd.DataFrame) and link_name in table.columns:
        return table[link_name].reindex(n.snapshots).fillna(default)
    return pd.Series(default, index=n.snapshots, dtype=float)


def get_link_parameter(link_name: str, parameter: str, default=np.nan):
    """Read a scalar Link parameter while tolerating older exported networks."""
    if parameter not in n.links.columns or link_name not in n.links.index:
        return default
    value = n.links.at[link_name, parameter]
    return default if pd.isna(value) else value


def state_blocks(state: pd.Series, snapshot_hours: pd.Series) -> pd.DataFrame:
    """Convert a Boolean operating state into consecutive on/off periods."""
    state = state.astype(bool)
    group = state.ne(state.shift()).cumsum()
    records = []
    for block_number, (_, block_state) in enumerate(state.groupby(group), start=1):
        block_index = block_state.index
        records.append({
            "block": block_number,
            "state": "on" if block_state.iloc[0] else "off",
            "start": block_index[0],
            "end": block_index[-1],
            "duration_h": snapshot_hours.loc[block_index].sum(),
        })
    return pd.DataFrame(records)

# --------------------------
# 1) PTES charging / discharging power
# --------------------------
charger = -n.links_t.p0["Hoje Taastrup PTES charger"]
discharger = n.links_t.p0["Hoje Taastrup PTES discharger"]

plt.figure(figsize=(12, 4))
charger.plot(label="PTES charging [MW]")
discharger.plot(label="PTES discharging [MW]")
plt.axhline(0, linewidth=0.8, color="black")
plt.ylabel("Power [MW]")
plt.xlabel("Time")
plt.legend()
save_fig("ptes_charge_discharge.png")

# --------------------------
# 2) Marginal heat price (DH CPH generator MC time series)
# --------------------------
# Note: marginal_cost is static in many models; in yours you set it as a time series.
# Use .loc if needed, but here it should already align with snapshots.
marginal_price_heat = n.generators_t.marginal_cost["DH CPH"]

plt.figure(figsize=(12, 4.8))
ax = plt.gca()

ax.plot(
    marginal_price_heat.index,
    marginal_price_heat,
    label="Dynamic tariff",
    linewidth=1.8,
    #linestyle="--",
    color="dimgray"
)

ax.axhline(0, linewidth=0.8, color="black")

ax.set_ylabel("Dynamic tariff [DKK/MWh]")
ax.set_xlabel("Time")
ax.set_title("Dynamic tariff")
ax.legend(loc="upper right", frameon=True)

ax.set_xlim(marginal_price_heat.index.min(), marginal_price_heat.index.max())

save_fig("dynamic_tariff_clean.png")
# --------------------------
# 3) PTES state of charge (SOC)
# --------------------------
soc = n.stores_t.e["Hoje Taastrup PTES storage"]

plt.figure(figsize=(12, 4))
soc.plot()
plt.ylabel("Energy content [MWh]")
plt.xlabel("Time")
plt.title("PTES State of Charge")
save_fig("ptes_soc.png")

# --------------------------
# 4) Equivalent full cycles (printed)
# --------------------------
E_capacity = 3300.0  # MWh (your e_nom)

soc_diff = soc.diff().fillna(0.0)
E_charge_total = soc_diff[soc_diff > 0].sum()
E_discharge_total = -soc_diff[soc_diff < 0].sum()
cycles = E_discharge_total / E_capacity if E_capacity > 0 else float("nan")

print(f"Total charged energy:   {E_charge_total:.1f} MWh")
print(f"Total discharged energy:{E_discharge_total:.1f} MWh")
print(f"Equivalent full cycles: {cycles:.2f}")

# --------------------------
# 5) Heat demand
# --------------------------
demand = n.loads_t.p["Hoje Taastrup DH load"]  # MW_th

demand_total = demand.sum()

print(f"Total heat demand: {demand_total:.1f} MWh_th")

plt.figure(figsize=(12, 4))
demand.plot()
plt.ylabel("Heat demand [MW_th]")
plt.xlabel("Time")
plt.title("Høje Taastrup District Heating Demand")
save_fig("heat_demand.png")

# --------------------------
# 6) Detailed heat-pump operation and cycling diagnostics
# --------------------------
# PyPSA Link sign convention used here:
#   p0 > 0  electricity consumed at bus0
#   p1 > 0  heat extracted from the source bus (negative Link efficiency)
#  -p2 > 0  useful heat delivered to the district-heating bus
if isinstance(n.snapshot_weightings, pd.DataFrame):
    weighting_column = (
        "generators"
        if "generators" in n.snapshot_weightings.columns
        else n.snapshot_weightings.columns[0]
    )
    snapshot_hours = n.snapshot_weightings[weighting_column].reindex(n.snapshots)
else:
    snapshot_hours = pd.Series(1.0, index=n.snapshots)
snapshot_hours = snapshot_hours.fillna(1.0).astype(float)
modelled_hours = snapshot_hours.sum()

hp_results = {}
hp_summary_rows = []
hp_monthly_frames = []
hp_block_frames = []

for hp_label, hp_config in HEAT_PUMPS.items():
    link_name = hp_config["link"]
    thermal_capacity = hp_config["thermal_capacity_mw"]

    electrical_input = get_link_series("p0", link_name).clip(lower=0.0)
    source_heat = get_link_series("p1", link_name).clip(lower=0.0)
    heat_output = (-get_link_series("p2", link_name)).clip(lower=0.0)

    p_nom = float(get_link_parameter(link_name, "p_nom", np.nan))
    p_min_pu = float(get_link_parameter(link_name, "p_min_pu", 0.0))
    p_max_pu = float(get_link_parameter(link_name, "p_max_pu", 1.0))
    min_up_time = float(get_link_parameter(link_name, "min_up_time", 0.0))
    min_down_time = float(get_link_parameter(link_name, "min_down_time", 0.0))
    start_up_cost = float(get_link_parameter(link_name, "start_up_cost", 0.0))

    if p_nom > EPS:
        electrical_load_pu = electrical_input / p_nom
    else:
        electrical_load_pu = pd.Series(np.nan, index=n.snapshots)

    status_table = getattr(n.links_t, "status", None)
    has_optimized_status = (
        isinstance(status_table, pd.DataFrame) and link_name in status_table.columns
    )
    if has_optimized_status:
        status = get_link_series("status", link_name) > 0.5
        status_source = "optimized commitment variable"
    else:
        status = electrical_input > EPS
        status_source = "inferred from electrical dispatch"

    start_up_table = getattr(n.links_t, "start_up", None)
    if isinstance(start_up_table, pd.DataFrame) and link_name in start_up_table.columns:
        start_events = get_link_series("start_up", link_name).clip(lower=0.0)
    else:
        start_events = (status & ~status.shift(fill_value=False)).astype(float)

    shut_down_table = getattr(n.links_t, "shut_down", None)
    if isinstance(shut_down_table, pd.DataFrame) and link_name in shut_down_table.columns:
        shut_down_events = get_link_series("shut_down", link_name).clip(lower=0.0)
    else:
        shut_down_events = (~status & status.shift(fill_value=False)).astype(float)

    actual_cop = (heat_output / electrical_input).where(electrical_input > EPS)
    p_min_pu_ts = get_link_series("p_min_pu", link_name, p_min_pu)
    p_max_pu_ts = get_link_series("p_max_pu", link_name, p_max_pu)

    blocks = state_blocks(status, snapshot_hours)
    blocks.insert(0, "heat_pump", hp_label)
    blocks.insert(1, "link", link_name)
    blocks["boundary_censored"] = False
    if not blocks.empty:
        blocks.loc[blocks.index[[0, -1]], "boundary_censored"] = True
    hp_block_frames.append(blocks)

    on_blocks = blocks.loc[blocks["state"] == "on", "duration_h"]
    off_blocks = blocks.loc[blocks["state"] == "off", "duration_h"]

    heat_energy = (heat_output * snapshot_hours).sum()
    electricity_energy = (electrical_input * snapshot_hours).sum()
    source_energy = (source_heat * snapshot_hours).sum()
    operating_hours = (status.astype(float) * snapshot_hours).sum()
    starts = start_events.sum()
    shutdowns = shut_down_events.sum()

    active_load = electrical_load_pu.where(status)
    near_min = status & (electrical_load_pu <= p_min_pu_ts + 0.05 + EPS)
    near_full = status & (electrical_load_pu >= 0.95 * p_max_pu_ts - EPS)
    part_load = status & ~near_min & ~near_full
    min_load_violations = status & (electrical_load_pu < p_min_pu_ts - EPS)
    max_load_violations = electrical_load_pu > p_max_pu_ts + EPS
    off_dispatch_violations = ~status & (electrical_input > EPS)
    large_output_changes = heat_output.diff().abs() > 0.50 * thermal_capacity + EPS

    hp_summary_rows.append({
        "heat_pump": hp_label,
        "status_source": status_source,
        "thermal_capacity_mw": thermal_capacity,
        "electrical_p_nom_mw": p_nom,
        "minimum_load_pu": p_min_pu,
        "minimum_up_time_h": min_up_time,
        "minimum_down_time_h": min_down_time,
        "heat_output_mwh": heat_energy,
        "electricity_input_mwh": electricity_energy,
        "source_heat_mwh": source_energy,
        "seasonal_cop": heat_energy / electricity_energy if electricity_energy > EPS else np.nan,
        "equivalent_full_load_hours": heat_energy / thermal_capacity,
        "capacity_factor_pct": 100.0 * heat_energy / (thermal_capacity * modelled_hours),
        "operating_hours": operating_hours,
        "operating_share_pct": 100.0 * operating_hours / modelled_hours,
        "number_of_observed_runs": len(on_blocks),
        "starts": starts,
        "shutdowns": shutdowns,
        "starts_per_1000_operating_h": (
            1000.0 * starts / operating_hours if operating_hours > EPS else np.nan
        ),
        "startup_cost_dkk": starts * start_up_cost,
        "mean_run_duration_h": on_blocks.mean(),
        "median_run_duration_h": on_blocks.median(),
        "minimum_run_duration_h": on_blocks.min(),
        "maximum_run_duration_h": on_blocks.max(),
        "one_hour_runs": int((on_blocks <= 1.0 + EPS).sum()),
        "one_hour_run_share_pct": (
            100.0 * (on_blocks <= 1.0 + EPS).sum() / len(on_blocks)
            if len(on_blocks) > 0 else np.nan
        ),
        "runs_shorter_than_min_up_time": int(
            (on_blocks < min_up_time - EPS).sum() if min_up_time > 0 else 0
        ),
        "off_periods_shorter_than_min_down_time": int(
            (off_blocks < min_down_time - EPS).sum() if min_down_time > 0 else 0
        ),
        "mean_off_duration_h": off_blocks.mean(),
        "median_off_duration_h": off_blocks.median(),
        "mean_heat_output_when_on_mw": heat_output.where(status).mean(),
        "maximum_heat_output_mw": heat_output.max(),
        "mean_electrical_load_when_on_pu": active_load.mean(),
        "near_minimum_load_hours": (near_min.astype(float) * snapshot_hours).sum(),
        "part_load_hours": (part_load.astype(float) * snapshot_hours).sum(),
        "near_full_load_hours": (near_full.astype(float) * snapshot_hours).sum(),
        "near_minimum_share_of_on_pct": (
            100.0 * (near_min.astype(float) * snapshot_hours).sum() / operating_hours
            if operating_hours > EPS else np.nan
        ),
        "part_load_share_of_on_pct": (
            100.0 * (part_load.astype(float) * snapshot_hours).sum() / operating_hours
            if operating_hours > EPS else np.nan
        ),
        "near_full_share_of_on_pct": (
            100.0 * (near_full.astype(float) * snapshot_hours).sum() / operating_hours
            if operating_hours > EPS else np.nan
        ),
        "minimum_load_violation_hours": (
            min_load_violations.astype(float) * snapshot_hours
        ).sum(),
        "maximum_load_violation_hours": (
            max_load_violations.astype(float) * snapshot_hours
        ).sum(),
        "off_but_dispatching_hours": (
            off_dispatch_violations.astype(float) * snapshot_hours
        ).sum(),
        "output_changes_above_50pct_capacity": int(large_output_changes.sum()),
    })

    monthly = pd.DataFrame({
        "heat_output_mwh": heat_output * snapshot_hours,
        "electricity_input_mwh": electrical_input * snapshot_hours,
        "source_heat_mwh": source_heat * snapshot_hours,
        "operating_hours": status.astype(float) * snapshot_hours,
        "starts": start_events,
        "modelled_hours": snapshot_hours,
        "load_pu_hours": electrical_load_pu.fillna(0.0) * snapshot_hours,
    }).resample("MS").sum()
    monthly["seasonal_cop"] = (
        monthly["heat_output_mwh"] / monthly["electricity_input_mwh"]
    ).where(monthly["electricity_input_mwh"] > EPS)
    monthly["equivalent_full_load_hours"] = (
        monthly["heat_output_mwh"] / thermal_capacity
    )
    monthly["capacity_factor_pct"] = (
        100.0
        * monthly["heat_output_mwh"]
        / (thermal_capacity * monthly["modelled_hours"])
    )
    monthly["mean_electrical_load_pu"] = (
        monthly["load_pu_hours"] / monthly["operating_hours"]
    ).where(monthly["operating_hours"] > EPS)
    monthly.insert(0, "heat_pump", hp_label)
    monthly.index.name = "month"
    hp_monthly_frames.append(monthly.reset_index())

    hp_results[hp_label] = {
        "heat": heat_output,
        "electricity": electrical_input,
        "source": source_heat,
        "cop": actual_cop,
        "load_pu": electrical_load_pu,
        "status": status,
        "starts": start_events,
        "capacity": thermal_capacity,
        "on_blocks": on_blocks,
    }

hp_summary = pd.DataFrame(hp_summary_rows).set_index("heat_pump")
hp_monthly = pd.concat(hp_monthly_frames, ignore_index=True)
hp_blocks = pd.concat(hp_block_frames, ignore_index=True)

hp_heat_total = hp_summary["heat_output_mwh"].sum()
print("\n--- Heat-pump annual performance ---")
print(hp_summary[[
    "heat_output_mwh",
    "electricity_input_mwh",
    "seasonal_cop",
    "equivalent_full_load_hours",
    "capacity_factor_pct",
    "operating_hours",
]].round(2).to_string())
print(f"Total heat-pump heat output: {hp_heat_total:.1f} MWh_th")

print("\n--- Heat-pump cycling and commitment ---")
print(hp_summary[[
    "starts",
    "shutdowns",
    "starts_per_1000_operating_h",
    "mean_run_duration_h",
    "median_run_duration_h",
    "one_hour_runs",
    "one_hour_run_share_pct",
    "near_minimum_share_of_on_pct",
    "part_load_share_of_on_pct",
    "near_full_share_of_on_pct",
    "runs_shorter_than_min_up_time",
    "off_periods_shorter_than_min_down_time",
    "minimum_load_violation_hours",
    "output_changes_above_50pct_capacity",
    "startup_cost_dkk",
]].round(2).to_string())
for hp_label, row in hp_summary.iterrows():
    print(
        f"{hp_label} status: {row['status_source']}; "
        f"minimum up/down time = {row['minimum_up_time_h']:.0f}/"
        f"{row['minimum_down_time_h']:.0f} h."
    )

summary_path = os.path.join(PLOT_DIR, "heat_pump_annual_summary.csv")
monthly_path = os.path.join(PLOT_DIR, "heat_pump_monthly_summary.csv")
blocks_path = os.path.join(PLOT_DIR, "heat_pump_operating_periods.csv")
hp_summary.to_csv(summary_path)
hp_monthly.to_csv(monthly_path, index=False)
hp_blocks.to_csv(blocks_path, index=False)
print(f"Saved diagnostics: {summary_path}")
print(f"Saved diagnostics: {monthly_path}")
print(f"Saved diagnostics: {blocks_path}")

# Annual heat production and electrical consumption.
plt.figure(figsize=(12, 4))
for hp_label, result in hp_results.items():
    result["heat"].plot(label=f"{hp_label} heat output")
plt.axhline(0, linewidth=0.8, color="black")
plt.ylabel("Heat production [MW_th]")
plt.xlabel("Time")
plt.title("Heat Pump Heat Production")
plt.legend()
save_fig("heat_pump_production.png")

plt.figure(figsize=(12, 4))
for hp_label, result in hp_results.items():
    result["electricity"].plot(label=f"{hp_label} electricity input")
plt.axhline(0, linewidth=0.8, color="black")
plt.ylabel("Electricity consumption [MW_el]")
plt.xlabel("Time")
plt.title("Heat Pump Electricity Consumption")
plt.legend()
save_fig("heat_pump_electricity.png")

# A load-duration curve makes operation at either zero or maximum immediately visible.
plt.figure(figsize=(8, 4.8))
for hp_label, result in hp_results.items():
    sorted_load = result["load_pu"].fillna(0.0).sort_values(ascending=False).to_numpy()
    duration_pct = 100.0 * np.arange(1, len(sorted_load) + 1) / len(sorted_load)
    plt.plot(duration_pct, sorted_load, linewidth=1.8, label=hp_label)
plt.axhline(0.25, color="dimgray", linestyle="--", linewidth=1.0, label="25% minimum load")
plt.xlabel("Share of modelled hours [%]")
plt.ylabel("Electrical loading [p.u. of p_nom]")
plt.title("Heat Pump Load-Duration Curve")
plt.ylim(bottom=0)
plt.legend()
save_fig("heat_pump_load_duration_curve.png")

# Heat output and start count by month show whether cycling is seasonal.
fig, axes = plt.subplots(len(HEAT_PUMPS), 1, figsize=(12, 7), sharex=True)
axes = np.atleast_1d(axes)
for ax, hp_label in zip(axes, HEAT_PUMPS):
    monthly = hp_monthly.loc[hp_monthly["heat_pump"] == hp_label].copy()
    month_labels = monthly["month"].dt.strftime("%b")
    ax.bar(month_labels, monthly["heat_output_mwh"], color="tab:blue", alpha=0.75)
    ax.set_ylabel("Heat [MWh_th]")
    ax.set_title(hp_label)
    ax2 = ax.twinx()
    ax2.plot(month_labels, monthly["starts"], color="tab:red", marker="o", label="Starts")
    ax2.set_ylabel("Starts")
fig.suptitle("Monthly Heat-Pump Production and Starts")
save_fig("heat_pump_monthly_production_and_starts.png")

# Count runs in duration classes; the first two bars expose one- and two-hour cycling.
duration_bins = [0, 1, 2, 5, 12, 24, np.inf]
duration_labels = ["1 h", "2 h", "3-5 h", "6-12 h", "13-24 h", ">24 h"]
duration_counts = {}
for hp_label, result in hp_results.items():
    duration_class = pd.cut(
        result["on_blocks"],
        bins=duration_bins,
        labels=duration_labels,
        include_lowest=True,
    )
    duration_counts[hp_label] = duration_class.value_counts(sort=False)
duration_counts = pd.DataFrame(duration_counts).fillna(0)
ax = duration_counts.plot.bar(figsize=(9, 4.8), width=0.8)
ax.set_xlabel("Consecutive operating-period duration")
ax.set_ylabel("Number of operating periods")
ax.set_title("Heat Pump Run-Duration Distribution")
ax.tick_params(axis="x", rotation=0)
save_fig("heat_pump_run_duration_distribution.png")

# Automatically zoom into the 168-hour interval with the highest combined starts.
combined_starts = sum(result["starts"] for result in hp_results.values())
window_length = min(168, len(n.snapshots))
rolling_starts = combined_starts.rolling(
    window_length,
    min_periods=window_length,
).sum()
window_end = rolling_starts.idxmax()
window_end_position = n.snapshots.get_loc(window_end)
window_start_position = max(0, window_end_position - window_length + 1)
zoom_index = n.snapshots[window_start_position:window_end_position + 1]

fig, axes = plt.subplots(len(HEAT_PUMPS), 1, figsize=(12, 7), sharex=True)
axes = np.atleast_1d(axes)
for ax, (hp_label, result) in zip(axes, hp_results.items()):
    heat_zoom = result["heat"].loc[zoom_index]
    start_zoom = result["starts"].loc[zoom_index] > 0.5
    ax.step(heat_zoom.index, heat_zoom, where="post", linewidth=1.8, label="Heat output")
    ax.scatter(
        heat_zoom.index[start_zoom],
        heat_zoom.loc[start_zoom],
        color="tab:red",
        marker="^",
        s=35,
        zorder=3,
        label="Start",
    )
    ax.axhline(
        result["capacity"],
        color="dimgray",
        linestyle="--",
        linewidth=1.0,
        label="Nominal thermal capacity",
    )
    ax.set_ylabel("Heat [MW_th]")
    ax.set_title(hp_label)
    ax.legend(loc="upper right")
axes[-1].set_xlabel("Time")
fig.suptitle("Most Start-Intensive 168-Hour Heat-Pump Period")
save_fig("heat_pump_most_start_intensive_week.png")


# --------------------------
# 7) PTES operational diagnostics
# --------------------------
# Use positive dispatch values for diagnostics. For a PyPSA Link, p0 is normally
# positive in the direction bus0 -> bus1. The PTES charger and discharger were
# both defined in their physical direction, so p0 gives positive charge/discharge.
# The clip is just a numerical safeguard against tiny negative values.
PTES_CHARGE_MIN_MW = 10.0
PTES_DISCHARGE_MIN_MW = 5.0
PTES_RAMP_LIMIT_MW_PER_H = 12.0

ptes_charge = n.links_t.p0["Hoje Taastrup PTES charger"].clip(lower=0.0)
ptes_discharge = n.links_t.p0["Hoje Taastrup PTES discharger"].clip(lower=0.0)

is_charging = ptes_charge > EPS
is_discharging = ptes_discharge > EPS

charge_hours = int(is_charging.sum())
discharge_hours = int(is_discharging.sum())
charge_starts = int((is_charging & ~is_charging.shift(fill_value=False)).sum())
discharge_starts = int((is_discharging & ~is_discharging.shift(fill_value=False)).sum())

simultaneous_hours = int((is_charging & is_discharging).sum())
small_charge_hours = int(((ptes_charge > EPS) & (ptes_charge < PTES_CHARGE_MIN_MW - EPS)).sum())
small_discharge_hours = int(((ptes_discharge > EPS) & (ptes_discharge < PTES_DISCHARGE_MIN_MW - EPS)).sum())

charge_diff = ptes_charge.diff().dropna()
discharge_diff = ptes_discharge.diff().dropna()
charge_ramp_violations = int((charge_diff.abs() > PTES_RAMP_LIMIT_MW_PER_H + EPS).sum())
discharge_ramp_violations = int((discharge_diff.abs() > PTES_RAMP_LIMIT_MW_PER_H + EPS).sum())

# Link-based throughput is often more meaningful than SOC differences for
# equivalent-cycle diagnostics, because SOC differences also reflect standing loss
# and initial/final SOC effects.
link_charged_energy = ptes_charge.sum()
link_discharged_energy = ptes_discharge.sum()
link_cycles = link_discharged_energy / E_capacity if E_capacity > 0 else float("nan")

print("\n--- PTES operational diagnostics ---")
print(f"Link-based charged energy:       {link_charged_energy:.1f} MWh")
print(f"Link-based discharged energy:    {link_discharged_energy:.1f} MWh")
print(f"Link-based equivalent cycles:    {link_cycles:.2f}")
print(f"Charging hours:                  {charge_hours}")
print(f"Discharging hours:               {discharge_hours}")
print(f"Charge starts:                   {charge_starts}")
print(f"Discharge starts:                {discharge_starts}")
print(f"Average charge power when active:{ptes_charge[is_charging].mean():.2f} MW")
print(f"Average discharge power active:  {ptes_discharge[is_discharging].mean():.2f} MW")
print(f"Simultaneous charge/discharge:   {simultaneous_hours} hours")
print(f"Charge hours below 10 MW:        {small_charge_hours}")
print(f"Discharge hours below 5 MW:      {small_discharge_hours}")
print(f"Max charge ramp up/down:         {charge_diff.max():.2f} / {charge_diff.min():.2f} MW/h")
print(f"Max discharge ramp up/down:      {discharge_diff.max():.2f} / {discharge_diff.min():.2f} MW/h")
print(f"Charge ramp violations:          {charge_ramp_violations}")
print(f"Discharge ramp violations:       {discharge_ramp_violations}")

if hasattr(n, "objective") and n.objective is not None:
    print(f"Objective value:                 {n.objective:.2f}")
else:
    print("Objective value:                 not available in exported network")

# Check the 2-hour no-reversal rule, if this model version includes it.
for k in [1, 2]:
    charge_to_discharge = int((is_charging.iloc[:-k].to_numpy() & is_discharging.iloc[k:].to_numpy()).sum())
    discharge_to_charge = int((is_discharging.iloc[:-k].to_numpy() & is_charging.iloc[k:].to_numpy()).sum())
    print(f"Charge -> discharge within {k}h: {charge_to_discharge}")
    print(f"Discharge -> charge within {k}h: {discharge_to_charge}")

# Save diagnostics as a small CSV so different model versions can be compared.
diagnostics = pd.Series({
    "soc_based_charged_energy_mwh": E_charge_total,
    "soc_based_discharged_energy_mwh": E_discharge_total,
    "soc_based_equivalent_cycles": cycles,
    "link_based_charged_energy_mwh": link_charged_energy,
    "link_based_discharged_energy_mwh": link_discharged_energy,
    "link_based_equivalent_cycles": link_cycles,
    "charge_hours": charge_hours,
    "discharge_hours": discharge_hours,
    "charge_starts": charge_starts,
    "discharge_starts": discharge_starts,
    "avg_charge_power_when_active_mw": ptes_charge[is_charging].mean(),
    "avg_discharge_power_when_active_mw": ptes_discharge[is_discharging].mean(),
    "simultaneous_charge_discharge_hours": simultaneous_hours,
    "charge_hours_below_10_mw": small_charge_hours,
    "discharge_hours_below_5_mw": small_discharge_hours,
    "max_charge_ramp_up_mw_per_h": charge_diff.max(),
    "max_charge_ramp_down_mw_per_h": charge_diff.min(),
    "max_discharge_ramp_up_mw_per_h": discharge_diff.max(),
    "max_discharge_ramp_down_mw_per_h": discharge_diff.min(),
    "charge_ramp_violations": charge_ramp_violations,
    "discharge_ramp_violations": discharge_ramp_violations,
})

diagnostics_path = os.path.join(PLOT_DIR, "ptes_operational_diagnostics.csv")
diagnostics.to_csv(diagnostics_path, header=["value"])
print(f"Saved diagnostics: {diagnostics_path}")

# --------------------------
# 9) Electricity price
# --------------------------
electricity_price_data = pd.read_csv(
    "/Data/Elspotprices.csv",
    sep=";"
)

electricity_price_data["time"] = pd.to_datetime(electricity_price_data["HourUTC"])
electricity_price_data = electricity_price_data.set_index("time").sort_index()

# Convert price format (comma → dot)
s = electricity_price_data["SpotPriceDKK"].astype(str).str.replace(",", ".", regex=False)
price = pd.to_numeric(s, errors="coerce")

# Align to model snapshots (important!)
price = price.reindex(n.snapshots).ffill().bfill()

# Plot

plt.figure(figsize=(12, 4.8))
ax = plt.gca()

ax.plot(
    price.index,
    price,
    label="Electricity price",
    linewidth=1.8,
    color="tab:blue"
)

ax.axhline(0, linewidth=0.8, color="black")

ax.set_ylabel("Electricity price [DKK/MWh]")
ax.set_xlabel("Time")
ax.set_title("Electricity price (DK1)")
ax.legend(loc="upper right", frameon=True)

ax.set_xlim(price.index.min(), price.index.max())

save_fig("electricity_price_clean.png")

# --------------------------
# Combined plot: Electricity price and dynamic tariff
# --------------------------
plt.figure(figsize=(12, 4.8))
ax1 = plt.gca()
ax2 = ax1.twinx()

# Electricity price
ax1.plot(
    price.index,
    price,
    label="Electricity price",
    linewidth=1.8,
    color="tab:blue",
    alpha=0.9
)

# Dynamic tariff / marginal heat cost
ax2.plot(
    marginal_price_heat.index,
    marginal_price_heat,
    label="Dynamic tariff",
    linewidth=2.0,
    linestyle="--",
    color="dimgray"
)

# Zero line for price axis
ax1.axhline(0, linewidth=0.8, color="black")

# Labels and title
ax1.set_ylabel("Electricity price [DKK/MWh]")
ax2.set_ylabel("Dynamic tariff [DKK/MWh]")
ax1.set_xlabel("Time")
ax1.set_title("Electricity price and dynamic tariff")

# Start y-axes at zero where sensible
ax2.set_ylim(bottom=0)

# Combined legend
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", frameon=True)

save_fig("electricity_price_dynamic_tariff.png")

############################

plt.figure(figsize=(12, 4))
ax1 = plt.gca()
ax2 = ax1.twinx()

soc.plot(ax=ax1, label="PTES SOC [MWh]")
marginal_price_heat.plot(ax=ax2, label="Dynamic tariff [DKK/MWh]")

ax1.set_ylabel("SOC [MWh]")
ax2.set_ylabel("Tariff [DKK/MWh]")
ax1.set_xlabel("Time")
ax1.set_title("PTES State of Charge and Dynamic Tariff")

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

save_fig("soc_tariff_full.png")

start = "2024-01-15"
end = "2024-01-22"

plt.figure(figsize=(12, 4))
ax1 = plt.gca()
ax2 = ax1.twinx()

soc.loc[start:end].plot(ax=ax1, label="PTES SOC [MWh]")
marginal_price_heat.loc[start:end].plot(ax=ax2, label="Dynamic tariff [DKK/MWh]")

ax1.set_ylabel("SOC [MWh]")
ax2.set_ylabel("Tariff [DKK/MWh]")
ax1.set_xlabel("Time")
ax1.set_title("PTES SOC and Dynamic Tariff (Zoom)")

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

save_fig("soc_tariff_zoom.png")

plt.figure(figsize=(12, 4))
ax1 = plt.gca()
ax2 = ax1.twinx()

price.plot(ax=ax1, label="Electricity price [DKK/MWh]")
marginal_price_heat.plot(ax=ax2, label="Dynamic tariff [DKK/MWh]")

ax1.set_ylabel("Electricity price [DKK/MWh]")
ax2.set_ylabel("Tariff [DKK/MWh]")
ax1.set_xlabel("Time")
ax1.set_title("Electricity Price and Dynamic Tariff")

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

save_fig("price_tariff_full.png")

# --------------------------
# Zoom-in plot: PTES operation and dynamic tariff
# --------------------------
start = "2024-01-15 00:00"
end = "2024-01-18 06:00"

charge_zoom = -charger.loc[start:end].copy()
discharge_zoom = -discharger.loc[start:end].copy()
tariff_zoom = marginal_price_heat.loc[start:end].copy()

plt.figure(figsize=(12, 4.8))
ax1 = plt.gca()
ax2 = ax1.twinx()

ax1.plot(
    charge_zoom.index,
    charge_zoom,
    label="Charging",
    linewidth=2.5,
    color="tab:blue"
)
ax1.plot(
    discharge_zoom.index,
    discharge_zoom,
    label="Discharging",
    linewidth=2.5,
    color="tab:orange"
)
ax1.axhline(0, color="black", linewidth=0.8)

ax2.plot(
    tariff_zoom.index,
    tariff_zoom,
    label="Dynamic tariff",
    linewidth=2.2,
    linestyle="--",
    color="dimgray"
)

ax1.set_ylabel("PTES power [MW]")
ax2.set_ylabel("Tariff [DKK/MWh]")
ax1.set_xlabel("Time")
ax1.set_title("PTES operation under dynamic tariff (zoom)")

ax1.set_xlim(tariff_zoom.index.min(), tariff_zoom.index.max())

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", frameon=True)

save_fig("ptes_operation_tariff_zoom_clean.png")
# --------------------------
# Zoom-in plot: Heat exchanger operation and dynamic tariff
# --------------------------
start = "2024-01-15 00:00"
end = "2024-01-18 06:00"

hex_zoom = -n.links_t.p1["HX Hoje Taastrup"].loc[start:end].copy()   # adjust sign/port if needed
tariff_zoom = marginal_price_heat.loc[start:end].copy()

plt.figure(figsize=(12, 4.8))
ax1 = plt.gca()
ax2 = ax1.twinx()

ax1.plot(
    hex_zoom.index,
    hex_zoom,
    label="Heat exchanger",
    linewidth=2.5,
    color="tab:green"
)
ax1.axhline(0, color="black", linewidth=0.8)

ax2.plot(
    tariff_zoom.index,
    tariff_zoom,
    label="Dynamic tariff",
    linewidth=2.2,
    linestyle="--",
    color="dimgray"
)

ax1.set_ylabel("Heat output [MW]")
ax2.set_ylabel("Tariff [DKK/MWh]")
ax1.set_xlabel("Time")
ax1.set_title("Heat exchanger operation under dynamic tariff (zoom)")

ax1.set_xlim(tariff_zoom.index.min(), tariff_zoom.index.max())

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", frameon=True)

save_fig("heat_exchanger_tariff_zoom.png")

#n.statistics.energy_balance.plot()

#eb = n.statistics.energy_balance(groupby_time=False, bus_carrier="heat", groupby=["carrier"])
#eb_T = eb.T

#eb_pos = eb_T.clip(lower=0)
#eb_neg = eb_T.clip(upper=0)

#ax = eb_pos.plot.area(figsize=(14,4), linewidth=0, stacked=True)
#eb_neg.plot.area(ax=ax, linewidth=0, stacked=True, legend=False)

#ax.axhline(0, color="black", linewidth=0.8)
#ax.set_ylabel("Power [MW]")
#ax.set_title("Heat energy balance (by carrier)")
#plt.tight_layout()
#plt.show()

#eb = n.statistics.energy_balance(
#    groupby_time=False,               # MW time series
#    bus_carrier="heat",               # only heat buses
#    groupby=["carrier"],
#    direction="both",
#)
#
#eb_T = eb.T
#
#plt.figure(figsize=(14,4))
#ax = eb_T.plot.area(linewidth=0)
#ax.axhline(0, color="black", linewidth=0.8)
#ax.set_ylabel("Power [MW]")
#ax.set_title("Heat Energy Balance (by Carrier)")
#plt.tight_layout()
#plt.show()
