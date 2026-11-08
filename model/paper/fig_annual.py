"""Paper figure: the 52 weekly benchmarks of 2024 under the hourly discharge credit.

(a) Weekly system saving versus the monthly tariff, split into HTF bill saving
    and upstream aggregate gain, with the weekly coordination value.
(b) Weekly PTES discharge: coordinated schedule, monthly tariff, hourly credit.
Usage: python fig_annual.py <weekly_study_dir> <output_dir> [tariff]
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

study, output = Path(sys.argv[1]), Path(sys.argv[2])
tariff = sys.argv[3] if len(sys.argv) > 3 else "hourly_5_g025"
output.mkdir(parents=True, exist_ok=True)
ink, muted, grid = "#0b0b0b", "#52514e", "#e6e5e0"
blue, orange, aqua, grey = "#2a78d6", "#eb6834", "#1baf7a", "#9a9993"

table = pd.read_csv(study / "study.csv")
table["week"] = table.scenario.str.split("__").str[0]
case = table[table.tariff == tariff].set_index("week").sort_index()
reference = table[table.tariff == "reference"].set_index("week").sort_index()
central = pd.Series({w: pd.read_csv(study / f"{w}__base" / "central" / "dispatch.csv").ptes_discharge_mw.sum()
                     for w in case.index})
starts = pd.to_datetime([pd.read_csv(study / f"{w}__base" / "central" / "dispatch.csv", nrows=1).timestamp[0]
                         for w in case.index])

plt.rcParams.update({
    "font.family": "serif", "font.size": 8.5, "axes.spines.top": False,
    "axes.spines.right": False, "axes.edgecolor": muted, "xtick.color": muted,
    "ytick.color": muted, "legend.frameon": False, "legend.fontsize": 7.5,
})
fig, axes = plt.subplots(2, 1, figsize=(7.2, 4.6), sharex=True, constrained_layout=True)
x = np.arange(len(case))

ax = axes[0]
htf = case.local_bill_saving_dkk / 1e3
upstream = case.aggregate_upstream_operating_surplus_change_dkk / 1e3
ax.bar(x, upstream, 0.8, color=orange, label="Upstream aggregate gain")
ax.bar(x, htf, 0.8, bottom=upstream.clip(lower=0), color=blue, label="HTF bill saving")
ax.step(x, reference.system_cost_change_from_coordinated_dkk / 1e3, where="mid", color=ink, lw=1.0,
        label="Coordination value (monthly tariff vs. coordinated)")
ax.set_ylabel("Weekly saving vs.\nmonthly tariff [kDKK]")
ax.legend(loc="upper left", ncol=3, bbox_to_anchor=(0, 1.13))
ax.set_title("(a) Operating saving and its distribution", loc="left", pad=16)

ax = axes[1]
ax.step(x, central / 1e3, where="mid", color=grey, lw=1.4, label="Coordinated schedule")
ax.step(x, case.ptes_discharge_mwh / 1e3, where="mid", color=aqua, lw=1.2, label="HTF response, hourly credit")
ax.step(x, reference.ptes_discharge_mwh / 1e3, where="mid", color=ink, lw=1.0, label="HTF response, monthly tariff")
ax.set_ylabel("PTES discharge\n[GWh/week]")
ax.legend(loc="upper left", ncol=3, bbox_to_anchor=(0, 1.13))
ax.set_title("(b) PTES use", loc="left", pad=16)
months = [i for i in range(len(starts)) if i == 0 or starts[i].month != starts[i - 1].month]
ax.set_xticks(months, [starts[i].strftime("%b") for i in months])
ax.set_xlim(-0.6, len(x) - 0.4)

for ax in axes:
    ax.grid(axis="y", color=grid, lw=0.6)
    ax.set_axisbelow(True)
    ax.axhline(0, color=muted, lw=0.5)
for suffix in ["pdf", "png"]:
    fig.savefig(output / f"annual_weeks.{suffix}", dpi=300, bbox_inches="tight")
