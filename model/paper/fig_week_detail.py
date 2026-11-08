"""Paper figure: signals, credit and dispatch for two selected weeks.

Rows: (a) electricity price and conditional heat/storage values, (b) discharge
credit, (c) PTES net operation, (d) local heat-pump output.
Usage: python fig_week_detail.py <study_dir> <output_dir>
"""

import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

study, output = Path(sys.argv[1]), Path(sys.argv[2])
output.mkdir(parents=True, exist_ok=True)
weeks = {"w16__base": "Shoulder week (15–21 April)", "w29__base": "Summer week (15–21 July)"}

ink, muted, grid = "#0b0b0b", "#52514e", "#e6e5e0"
blue, orange, aqua, violet, grey = "#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#9a9993"

plt.rcParams.update({
    "font.family": "serif", "font.size": 8.5, "axes.spines.top": False,
    "axes.spines.right": False, "axes.edgecolor": muted, "xtick.color": muted,
    "ytick.color": muted, "axes.titlesize": 9, "legend.frameon": False, "legend.fontsize": 7.5,
})
fig, axes = plt.subplots(4, 2, figsize=(7.2, 7.6), sharex="col", constrained_layout=True,
                         gridspec_kw={"height_ratios": [1.2, 0.8, 1.1, 0.8]})


def read(week, case):
    frame = pd.read_csv(study / week / case / "dispatch.csv",
                        index_col="timestamp", parse_dates=True)
    frame.index = frame.index.tz_convert("Europe/Copenhagen")
    return frame


for j, (week, title) in enumerate(weeks.items()):
    central = read(week, "central")
    hourly = read(week, "hourly_5_g025_corrective")
    constant = read(week, "constant_5_corrective")
    measured = (study / week / "metered_corrective").exists()
    reference = read(week, "metered_corrective" if measured else "reference_corrective")
    credit = pd.read_csv(study / week / "hourly_5_g025_local" / "inputs.csv",
                         index_col="timestamp", parse_dates=True).discharge_discount_dkk_mwh
    credit.index = credit.index.tz_convert("Europe/Copenhagen")

    ax = axes[0, j]
    ax.plot(central.index, central.electricity_dkk_mwh, color=grey, lw=1.0, label="DK2 electricity price")
    ax.plot(central.index, central.conditional_delivered_heat_value_dkk_mwh, color=orange, lw=1.2,
            label=r"Delivered heat value $\mu_t/r$")
    ax.plot(central.index, central.conditional_inventory_value_dkk_mwh, color=blue, lw=1.2,
            label=r"Stored heat value $v_t$")
    ax.axhline(central.reference_tariff_dkk_mwh.iloc[0], color=ink, ls="--", lw=0.8, label=r"Monthly tariff $\tau_m$")
    ax.set_title(title)
    ax.set_ylim(-200, 1250)

    ax = axes[1, j]
    ax.step(credit.index, credit, where="post", color=aqua, lw=1.2, label=r"Hourly credit $\delta_t$ ($g=0.25$)")
    ax.axhline(5, color=grey, lw=1.0, label="Constant credit")
    ax.set_ylim(-0.5, 10.8)

    ax = axes[2, j]
    net = lambda f: f.ptes_discharge_mw - f.ptes_charge_mw
    ax.fill_between(central.index, net(central), step="post", color=grey, alpha=0.35, lw=0,
                    label="Coordinated schedule")
    ax.step(central.index, net(hourly), where="post", color=aqua, lw=1.2, label="HTF response, hourly credit")
    ax.step(central.index, net(reference), where="post", color=ink, lw=0.9,
            label="Measured 2024" if measured else "HTF response, monthly tariff")
    ax.set_ylim(-33, 33)

    ax = axes[3, j]
    hp = lambda f: f.city2_heat_mw + f.groundwater_heat_mw
    ax.fill_between(central.index, hp(central), step="post", color=grey, alpha=0.35, lw=0,
                    label="Coordinated schedule")
    ax.step(central.index, hp(hourly), where="post", color=aqua, lw=1.2, label="HTF, hourly credit")
    ax.set_ylim(0, 3.2)
    ax.set_xlim(central.index[0], central.index[-1])
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=12, tz=central.index.tz))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a", tz=central.index.tz))
    ax.xaxis.set_minor_locator(mdates.DayLocator(tz=central.index.tz))
    ax.tick_params(axis="x", which="major", length=0)

for ax in axes.flat:
    ax.grid(axis="y", color=grid, lw=0.6)
    ax.set_axisbelow(True)
    ax.axhline(0, color=muted, lw=0.5)
labels = ["(a) Price and value\n[DKK/MWh]", "(b) Discharge credit\n[DKK/MWh]",
          "(c) PTES net discharge\n[MW]", "(d) Local heat pumps\n[MW$_{\\mathrm{th}}$]"]
for i, label in enumerate(labels):
    axes[i, 0].set_ylabel(label)
    axes[i, 1].legend(loc="upper left", bbox_to_anchor=(1.01, 1.0))
for suffix in ["pdf", "png"]:
    fig.savefig(output / f"week_detail.{suffix}", dpi=300, bbox_inches="tight")
