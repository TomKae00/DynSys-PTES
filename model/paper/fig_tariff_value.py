"""Paper figure from the frozen study table (reports/selected_weeks_30mw/base.csv).

(a) Share of the coordination value each tariff recovers: joint operating saving
    versus the monthly reference, divided by the reference's gap to the
    coordinated schedule.
(b) How the joint saving is split between HTF and the upstream aggregate.
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

source, output = Path(sys.argv[1]), Path(sys.argv[2])
name = sys.argv[3] if len(sys.argv) > 3 else "tariff_value_capture"
output.mkdir(parents=True, exist_ok=True)

weeks = {"winter": "Winter", "shoulder": "Shoulder", "summer": "Summer"}
tariffs = {
    "constant_5": "Constant 5",
    "constant_10": "Constant 10",
    "constant_50": "Constant 50",
    "hourly_5_g025": "Hourly, g = 0.25",
    "hourly_5_g1": "Hourly, g = 1",
}
# Constants in a light-to-dark grey ramp, hourly candidates in two hues.
tariff_colours = ["#c6c5c0", "#9a9993", "#5f5e5a", "#1baf7a", "#6250d6"]
split_colours = {"HTF": "#2a78d6", "Upstream": "#eb6834"}
ink, muted, grid = "#0b0b0b", "#52514e", "#e6e5e0"

table = pd.read_csv(source)
table["week"] = table.scenario.str.split("__").str[0]
table = table.set_index(["week", "tariff"])
benchmark = table.xs("reference", level="tariff").system_cost_change_from_coordinated_dkk

plt.rcParams.update({
    "font.family": "serif", "font.size": 8.5, "axes.spines.top": False,
    "axes.spines.right": False, "axes.edgecolor": muted, "xtick.color": muted,
    "ytick.color": muted, "axes.titlesize": 9,
})
fig = plt.figure(figsize=(7.2, 5.0), constrained_layout=True)
grid_spec = fig.add_gridspec(2, 3, height_ratios=[1, 1.05])

# (a) recovered share of the coordination value
ax = fig.add_subplot(grid_spec[0, :])
width = 0.15
x = np.arange(len(weeks))
for i, (key, label) in enumerate(tariffs.items()):
    share = [100 * table.loc[(w, key), "system_operating_cost_saving_dkk"] / benchmark[w] for w in weeks]
    bars = ax.bar(x + (i - 2) * width, share, width * 0.9, color=tariff_colours[i], label=label)
    if key == "hourly_5_g025":
        for bar, value in zip(bars, share):
            ax.text(bar.get_x() + bar.get_width() / 2, value + 2, f"{value:.0f}%",
                    ha="center", va="bottom", fontsize=7, color=ink)
ax.set_xticks(x, [f"{weeks[w]}\ncoordination value {benchmark[w] / 1e3:.1f} kDKK" for w in weeks])
ax.set_ylabel("Recovered coordination\nvalue [%]")
ax.set_ylim(0, 110)
ax.axhline(100, color=ink, ls="--", lw=0.8)
ax.grid(axis="y", color=grid, lw=0.6)
ax.set_axisbelow(True)
ax.legend(ncol=5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.2), fontsize=7.5)
ax.set_title("(a) Share of the coordinated-schedule saving recovered by each tariff", loc="left", pad=22)

# (b) distribution of the joint saving
for j, (week, title) in enumerate(weeks.items()):
    ax = fig.add_subplot(grid_spec[1, j])
    rows = table.loc[week].loc[list(tariffs)]
    xb = np.arange(len(tariffs))
    ax.bar(xb - 0.19, rows.local_bill_saving_dkk / 1e3, 0.36, color=split_colours["HTF"], label="HTF bill saving")
    ax.bar(xb + 0.19, rows.aggregate_upstream_operating_surplus_change_dkk / 1e3, 0.36,
           color=split_colours["Upstream"], label="Upstream aggregate gain")
    ax.scatter(xb, rows.system_operating_cost_saving_dkk / 1e3, s=14, color=ink, zorder=3,
               label="Joint operating saving")
    ax.axhline(0, color=muted, lw=0.6)
    ax.set_xticks(xb, ["C5", "C10", "C50", "H.25", "H1"], fontsize=7.5)
    ax.grid(axis="y", color=grid, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_title(("(b) " if j == 0 else "") + title, fontsize=8.5)
    if j == 0:
        ax.set_ylabel("Change vs. monthly\nreference [kDKK/week]")
handles, labels = ax.get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.5, -0.06), fontsize=7.5)
for suffix in ["pdf", "png"]:
    fig.savefig(output / f"{name}.{suffix}", dpi=300, bbox_inches="tight")
