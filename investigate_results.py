#!/usr/bin/env python3
import os
import pypsa
import pandas as pd
import matplotlib.pyplot as plt

# --------------------------
# Settings
# --------------------------
NET_PATH = "results/hoje_taastrup_dh_optimized_2024.nc"
PLOT_DIR = "results/plots_first_draft"
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
start = "2023-01-15 00:00"
end = "2023-01-18 06:00"

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
start = "2023-01-15 00:00"
end = "2023-01-18 06:00"

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