"""Paper figure: annual effect of passing a share s of the storage value to HTF.

(a) Annual system saving, HTF bill saving, upstream aggregate gain and upstream
    heat-revenue change versus the share s (s = 0 is the monthly tariff).
(b) PTES discharge and the mean credit per discharged MWh.
Usage: python fig_value_share.py <value_share_study_dir> <output_dir>
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

study, output = Path(sys.argv[1]), Path(sys.argv[2])
output.mkdir(parents=True, exist_ok=True)
ink, muted, grid = "#0b0b0b", "#52514e", "#e6e5e0"
blue, orange, aqua = "#2a78d6", "#eb6834", "#1baf7a"

table = pd.read_csv(study / "study.csv")
table["share"] = table.tariff.map(lambda t: 0.0 if t == "reference" else float(t.split("_")[1]) / 10 ** (len(t.split("_")[1]) - 1))
annual = table.groupby("share").agg(
    system=("system_operating_cost_saving_dkk", "sum"),
    htf=("local_bill_saving_dkk", "sum"),
    upstream=("aggregate_upstream_operating_surplus_change_dkk", "sum"),
    revenue=("supplier_local_heat_revenue_change_dkk", "sum"),
    discharge=("ptes_discharge_mwh", "sum"),
)
# Credit actually paid per discharged MWh = lost heat revenue / discharge.
annual["credit_per_mwh"] = -annual.revenue / annual.discharge.where(annual.discharge > 0)
annual.to_csv(output / "value_share_annual.csv")

plt.rcParams.update({
    "font.family": "serif", "font.size": 8.5, "axes.spines.top": False,
    "axes.spines.right": False, "axes.edgecolor": muted, "xtick.color": muted,
    "ytick.color": muted, "legend.frameon": False, "legend.fontsize": 7.5,
})
fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.9), constrained_layout=True,
                         gridspec_kw={"width_ratios": [1.5, 1]})
s = annual.index
ax = axes[0]
ax.plot(s, annual.system / 1e6, color=ink, marker="o", ms=4, lw=1.4, label=r"System saving $\Delta C^{\mathrm{sys}}$")
ax.plot(s, annual.upstream / 1e6, color=orange, marker="o", ms=4, lw=1.4, label=r"Upstream gain $\Delta U$")
ax.plot(s, annual.htf / 1e6, color=blue, marker="o", ms=4, lw=1.4, label=r"HTF bill saving $\Delta B^{\mathrm{HTF}}$")
ax.plot(s, annual.revenue / 1e6, color=orange, ls="--", lw=1.0, label="Upstream heat-revenue change")
ax.axhline(0, color=muted, lw=0.6)
ax.set_xlabel("Share $s$ of the storage value passed to HTF")
ax.set_ylabel("Annual change vs.\nmonthly tariff [MDKK]")
ax.legend(loc="upper left", bbox_to_anchor=(0, 1.02))
ax.set_title("(a) Welfare and its distribution", loc="left")

ax = axes[1]
ax.plot(s, annual.discharge / 3300, color=aqua, marker="o", ms=4, lw=1.4)
ax.set_xlabel("Share $s$")
ax.set_ylabel("Equivalent full cycles [-]", color=ink)
ax.set_ylim(0, None)
ax.set_title("(b) PTES use", loc="left")
for a in axes:
    a.grid(axis="y", color=grid, lw=0.6)
    a.set_axisbelow(True)
    a.set_xticks(s)
for suffix in ["pdf", "png"]:
    fig.savefig(output / f"value_share.{suffix}", dpi=300, bbox_inches="tight")
print(annual.assign(**{c: annual[c] / 1e6 for c in ["system", "htf", "upstream", "revenue"]}).round(3))
