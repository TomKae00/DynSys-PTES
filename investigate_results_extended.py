#!/usr/bin/env python3
import os
import pypsa
import pandas as pd
import matplotlib.pyplot as plt

# --------------------------
# Settings
# --------------------------
NET_PATH = "results/hoje_taastrup_dh_optimized_2024_layer3a_no_reversal.nc"
#NET_PATH = "results/hoje_taastrup_dh_optimized_2024_layer3a_no_reversal.nc"
PLOT_DIR = "results/plots_constraints"
DPI = 300

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
# 6) Heat pump heat production (delivered to DH Hoje Taastrup is p2)
# --------------------------
hp_city2_heat = -n.links_t.p2["City 2 heat pump Hoje Taastrup"]
hp_gw_heat = -n.links_t.p2["Ground water sourced HP Hoje Taastrup"]

city2_heat_total = hp_city2_heat.sum()
gw_heat_total = hp_gw_heat.sum()
hp_heat_total = city2_heat_total + gw_heat_total

print(f"City2 HP heat:       {city2_heat_total:.1f} MWh_th")
print(f"Groundwater HP heat: {gw_heat_total:.1f} MWh_th")
print(f"Total HP heat:       {hp_heat_total:.1f} MWh_th")


# --------------------------
# 7) PTES operational diagnostics
# --------------------------
# Use positive dispatch values for diagnostics. For a PyPSA Link, p0 is normally
# positive in the direction bus0 -> bus1. The PTES charger and discharger were
# both defined in their physical direction, so p0 gives positive charge/discharge.
# The clip is just a numerical safeguard against tiny negative values.
EPS = 1e-4
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

plt.figure(figsize=(12, 4))
hp_city2_heat.plot(label="City2 HP heat output")
hp_gw_heat.plot(label="Groundwater HP heat output")
plt.axhline(0, linewidth=0.8, color="black")
plt.ylabel("Heat production [MW_th]")
plt.xlabel("Time")
plt.title("Heat Pump Heat Production")
plt.legend()
save_fig("heat_pump_production.png")

# --------------------------
# Optional: also save electricity consumption of HPs (positive)
# --------------------------
hp_city2_el = -n.links_t.p0["City 2 heat pump Hoje Taastrup"]
hp_gw_el = -n.links_t.p0["Ground water sourced HP Hoje Taastrup"]

plt.figure(figsize=(12, 4))
hp_city2_el.plot(label="City2 HP electricity")
hp_gw_el.plot(label="Groundwater HP electricity")
plt.axhline(0, linewidth=0.8, color="black")
plt.ylabel("Electricity consumption [MW_el]")
plt.xlabel("Time")
plt.title("Heat Pump Electricity Consumption")
plt.legend()
save_fig("heat_pump_electricity.png")

print(f"All plots saved to: {PLOT_DIR}")

# --------------------------
# 9) Electricity price
# --------------------------
electricity_price_data = pd.read_csv(
    "/home/tom/PycharmProjects/DynSys/Data/Elspotprices.csv",
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