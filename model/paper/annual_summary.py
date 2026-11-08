"""Annual totals and Pareto check from 52-week study tables.

Usage: python annual_summary.py <study.csv> [<study.csv> ...]
Prints per-tariff annual sums and how many weeks leave both HTF and upstream
no worse off (tolerance: combined solver gap of that week).
"""

import sys

import pandas as pd

frames = []
for path in sys.argv[1:]:
    frame = pd.read_csv(path)
    frame["week"] = frame.scenario.str.split("__").str[0]
    frames.append(frame)
table = pd.concat(frames).drop_duplicates(["week", "tariff"])

reference = table[table.tariff == "reference"].set_index("week")
coordination_value = reference.system_cost_change_from_coordinated_dkk.sum()
gap = table.combined_system_solver_gap_bound_dkk
table["both_win"] = (table.local_bill_saving_dkk >= -gap) & (
    table.aggregate_upstream_operating_surplus_change_dkk >= -gap
)
summary = table.groupby("tariff").agg(
    weeks=("week", "nunique"),
    system_saving_mdkk=("system_operating_cost_saving_dkk", "sum"),
    htf_saving_mdkk=("local_bill_saving_dkk", "sum"),
    upstream_gain_mdkk=("aggregate_upstream_operating_surplus_change_dkk", "sum"),
    heat_revenue_change_mdkk=("supplier_local_heat_revenue_change_dkk", "sum"),
    discharge_gwh=("ptes_discharge_mwh", "sum"),
    standing_loss_gwh=("ptes_standing_loss_mwh", "sum"),
    weeks_both_win=("both_win", "sum"),
    solver_gap_mdkk=("combined_system_solver_gap_bound_dkk", "sum"),
)
for column in summary.columns:
    if column.endswith("mdkk"):
        summary[column] /= 1e6
    if column.endswith("gwh"):
        summary[column] /= 1e3
summary["cycles"] = summary.discharge_gwh * 1e3 / 3300
summary["recovered_share"] = summary.system_saving_mdkk * 1e6 / coordination_value
pd.set_option("display.width", 200)
print(f"Coordination value (reference vs coordinated), sum of weeks: {coordination_value / 1e6:.3f} MDKK")
print(summary.round(3).to_string())
