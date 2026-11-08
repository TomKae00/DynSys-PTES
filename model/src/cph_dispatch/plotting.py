"""Static paper figures and source tables from accepted result exports, without solving."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .analysis import reconcile
from .observations import compare_observations, load_observations
from .results import add_diagnostics, producer_costs
from .workflow import benefits, case_metrics

COLORS = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#999999"]


def _read_case(folder, plants):
    d = pd.read_csv(folder / "dispatch.csv", index_col=0)
    d.index = pd.to_datetime(d.index, utc=True)
    s = json.loads((folder / "summary.json").read_text())
    return SimpleNamespace(dispatch=add_diagnostics(d, s["assumptions"], plants), summary=s)


def report(run, output, plants, *, observations=None, observation_kind=None):
    # Matplotlib is optional for optimisation-only installations.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    run, output = Path(run), Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Figure output already contains files; choose an empty directory")
    if (run / "dispatch.csv").exists():
        folders = {"dispatch": run}
    else:
        folders = {
            p.name: p for p in sorted(run.iterdir()) if p.is_dir() and (p / "dispatch.csv").exists()
        }
    if not folders:
        raise ValueError("No accepted dispatch exports in the requested run")
    cases = {label: _read_case(folder, plants) for label, folder in folders.items()}
    if observations is not None and observation_kind is None:
        raise ValueError("Declare --observation-kind soc_proxy or metered")
    obs = load_observations(observations, kind=observation_kind) if observations else None
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"run": str(run.resolve()), "matplotlib": matplotlib.__version__, "inputs": {}}
    for folder in folders.values():
        for name in ["dispatch.csv", "summary.json"]:
            path = folder / name
            manifest["inputs"][str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["plant_table_sha256"] = hashlib.sha256(plants.to_csv(index=False).encode()).hexdigest()
    with (
        TemporaryDirectory(prefix=".figures-", dir=output.parent) as temporary,
        plt.rc_context(
            {
                "font.family": "DejaVu Sans",
                "font.size": 9,
                "axes.spines.top": False,
                "axes.spines.right": False,
                "axes.grid": True,
                "grid.alpha": 0.18,
                "pdf.fonttype": 42,
                "svg.fonttype": "none",
                "axes.prop_cycle": plt.cycler(color=COLORS),
            }
        ),
    ):
        staging = Path(temporary)

        def save(fig, name):
            for extension in ["pdf", "svg", "png"]:
                fig.savefig(staging / f"{name}.{extension}", dpi=300, bbox_inches="tight")
            plt.close(fig)

        diagnostics = {}
        plotted = {k: v for k, v in cases.items() if not k.endswith("_local")}
        for label, case in plotted.items():
            d, s = case.dispatch.copy(), case.summary
            announced = cases.get("central", case).dispatch
            if announced.index.equals(d.index):
                for source, target in [
                    (
                        "conditional_delivered_heat_value_dkk_mwh",
                        "announced_delivered_heat_value_dkk_mwh",
                    ),
                    ("conditional_inventory_value_dkk_mwh", "announced_inventory_value_dkk_mwh"),
                ]:
                    if source in announced:
                        d[target] = announced[source]
            d.to_csv(staging / f"{label}_figure_data.csv", index_label="timestamp")
            fig, axes = plt.subplots(3, 1, figsize=(7.2, 6.7), sharex=True, layout="constrained")
            axes[0].stackplot(
                d.index,
                d.hx_mw,
                d.ptes_discharge_mw,
                d.city2_heat_mw,
                d.groundwater_heat_mw,
                labels=["Direct heat", "PTES discharge", "City2 HP", "Groundwater HP"],
            )
            axes[0].plot(d.index, d.htf_demand_mw, "k--", lw=1, label="HTF demand template")
            axes[0].set_ylabel("Heat [MW]")
            axes[0].legend(ncol=3, fontsize=7, loc="lower left", bbox_to_anchor=(0, 1.0))
            axes[1].plot(
                d.index, d.ptes_discharge_mw - d.ptes_charge_mw, label="PTES net discharge"
            )
            axes[1].axhline(0, color="black", lw=0.6)
            axes[1].set_ylabel("Net flow [MW]")
            axes[1].legend(ncol=3, fontsize=7)
            axes[2].plot(d.index, d.ptes_energy_mwh, label="Model inventory")
            if obs:
                joined, comparison = compare_observations(d, *obs)
                axes[2].plot(
                    joined.index,
                    joined.recorded_inventory_mwh,
                    "k--",
                    lw=1,
                    label="Recorded inventory (context)",
                )
                joined.to_csv(staging / f"{label}_recorded_comparison.csv", index_label="timestamp")
                diagnostics[label + "_observations"] = comparison
            axes[2].set_ylabel("PTES inventory [MWh]")
            axes[2].set_xlabel("Time [UTC]")
            axes[2].legend(fontsize=7)
            locator = mdates.AutoDateLocator(minticks=3, maxticks=7)
            axes[2].xaxis.set_major_locator(locator)
            axes[2].xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
            fig.suptitle(f"{label.replace('_', ' ')} · {len(d)} h · scenario model", fontsize=10)
            save(fig, label + "_operation")

            discount = d.get(
                "discharge_discount_dkk_mwh", s["assumptions"]["discharge_discount_dkk_mwh"]
            )
            fig, axes = plt.subplots(2, 1, figsize=(7.2, 4.6), sharex=True, layout="constrained")
            axes[0].plot(d.index, d.reference_tariff_dkk_mwh, label="Direct heat tariff")
            axes[0].plot(
                d.index, d.reference_tariff_dkk_mwh - discount, label="Discharge service price"
            )
            axes[0].plot(
                d.index, d.discharge_pump_cost_dkk_mwh_heat, label="Incremental discharge pumping"
            )
            axes[0].set_ylabel("HTF price [DKK/MWh]")
            axes[0].legend(fontsize=7, ncol=2)
            if "announced_delivered_heat_value_dkk_mwh" in d:
                axes[1].plot(
                    d.index,
                    d.announced_delivered_heat_value_dkk_mwh,
                    label="Announced delivered heat value",
                )
                axes[1].plot(
                    d.index,
                    d.announced_inventory_value_dkk_mwh
                    / s["assumptions"]["ptes"]["discharge_efficiency"],
                    label="Inventory opportunity value",
                )
                axes[1].set_ylabel("Conditional value\n[DKK/MWh discharged]")
            else:
                axes[1].plot(d.index, d.electricity_dkk_mwh, label="DK2 electricity spot price")
                axes[1].set_ylabel("Electricity [DKK/MWh]")
            axes[1].legend(fontsize=7)
            axes[1].set_xlabel("Time [UTC]")
            axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
            save(fig, label + "_prices")

            if s["assumptions"]["objective"] == "system":
                producer_costs(d, s["assumptions"], plants).to_csv(
                    staging / f"{label}_chp_joint_costs.csv", index=False
                )
                fig, axes = plt.subplots(
                    2, 1, figsize=(7.2, 4.3), sharex=True, layout="constrained"
                )
                for name in s["assumptions"]["upstream"]["accumulators"]:
                    axes[0].plot(d.index, d[name + "_net_discharge_mw"], label=name)
                    axes[1].plot(d.index, d[name + "_energy_mwh"], label=name)
                axes[0].set_ylabel("Net discharge [MW]")
                axes[0].axhline(0, color="black", lw=0.6)
                axes[0].legend(ncol=2, fontsize=7)
                axes[1].set(ylabel="Regional inventory [MWh]", xlabel="Time [UTC]")
                axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
                save(fig, label + "_regional_storage")
                columns = [
                    c
                    for c in d
                    if c.endswith("_heat_mw") and c not in ["city2_heat_mw", "groundwater_heat_mw"]
                ]
                fig, ax = plt.subplots(figsize=(7.2, 3.4), layout="constrained")
                ax.stackplot(
                    d.index,
                    *(d[c] for c in columns),
                    labels=[c.removesuffix("_heat_mw").replace("_", " ") for c in columns],
                )
                ax.set(ylabel="Upstream heat [MW]", xlabel="Time [UTC]")
                ax.legend(ncol=4, fontsize=6, loc="upper center", bbox_to_anchor=(0.5, 1.25))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
                save(fig, label + "_producers")
            diagnostics[label] = {
                "ptes_standing_loss_mwh": float(d.ptes_standing_loss_mwh.sum()),
                "ptes_conversion_loss_mwh": float(d.ptes_conversion_loss_mwh.sum()),
                "mean_inventory_mwh": float(d.ptes_energy_mwh.mean()),
                "local_heat_balance_max_residual_mw": float(
                    d.local_heat_balance_residual_mw.abs().max()
                ),
                "inventory_balance_max_residual_mwh": float(
                    d.ptes_balance_residual_mwh.abs().max()
                ),
            }
        if "reference_corrective" in cases and "central" in cases:
            ref = case_metrics(
                cases["central"], cases["reference_local"], cases["reference_corrective"]
            )
            rows = []
            for label in plotted:
                if label == "reference_corrective" or not label.endswith("_corrective"):
                    continue
                local = cases[label.removesuffix("_corrective") + "_local"]
                metrics = case_metrics(cases["central"], local, cases[label])
                rows.append({"tariff": label.removesuffix("_corrective"), **benefits(ref, metrics)})
                diagnostics[label + "_mechanism"] = reconcile(
                    cases["reference_corrective"].dispatch,
                    cases[label].dispatch,
                    cases["reference_corrective"].summary,
                    cases[label].summary,
                )
            if rows:
                table = pd.DataFrame(rows).set_index("tariff")
                table.to_csv(staging / "stakeholder_accounting.csv")
                fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4), layout="constrained")
                x = np.arange(len(table))
                axes[0].bar(x, table.system_operating_cost_saving_dkk / 1000, color=COLORS[2])
                axes[0].errorbar(
                    x,
                    table.system_operating_cost_saving_dkk / 1000,
                    yerr=table.combined_system_solver_gap_bound_dkk / 1000,
                    fmt="none",
                    color="black",
                    capsize=3,
                )
                axes[0].set_title("Operating savings ± solver gap", fontsize=9)
                axes[1].bar(
                    x - 0.17,
                    table.local_bill_saving_dkk / 1000,
                    width=0.34,
                    label="HTF bill saving",
                )
                axes[1].bar(
                    x + 0.17,
                    table.aggregate_upstream_operating_surplus_change_dkk / 1000,
                    width=0.34,
                    label="Aggregate upstream surplus change",
                )
                axes[1].legend(fontsize=6, loc="lower left", bbox_to_anchor=(0, 1.02))
                for ax in axes:
                    ax.axhline(0, color="black", lw=0.7)
                    ax.set_xticks(x, table.index, rotation=25, ha="right")
                    ax.set_ylabel("Change vs zero credit [thousand DKK]")
                save(fig, "stakeholder_effects")
        (staging / "diagnostics.json").write_text(
            json.dumps(diagnostics, indent=2, allow_nan=False)
        )
        manifest["observation_source"] = obs[1] if obs else None
        manifest["interpretation"] = (
            "Scenario dispatch and payments; recorded data are contextual, not causal validation"
        )
        (staging / "figure_manifest.json").write_text(json.dumps(manifest, indent=2))
        if output.exists():
            output.rmdir()
        staging.rename(output)
    return diagnostics


def plot_study(table, output):
    """One comparison per matched period/sensitivity; do not connect unrelated cases."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for name, group in table.groupby("scenario", sort=False):
        fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4), layout="constrained")
        x = np.arange(len(group))
        axes[0].errorbar(
            x,
            group.system_operating_cost_saving_dkk / 1000,
            yerr=group.combined_system_solver_gap_bound_dkk / 1000,
            fmt="o",
            capsize=3,
            color=COLORS[0],
        )
        axes[1].plot(x, group.ptes_discharge_mwh, "o", color=COLORS[2])
        axes[0].set_ylabel("Operating saving [thousand DKK]")
        axes[1].set_ylabel("PTES discharge [MWh]")
        for ax in axes:
            ax.set_xticks(x, group.tariff, rotation=35, ha="right", fontsize=7)
            ax.axhline(0, color="black", lw=0.6)
        fig.suptitle(name.replace("__", " · "), fontsize=10)
        for extension in ["pdf", "svg", "png"]:
            fig.savefig(
                Path(output) / f"{name}_tariff_response.{extension}", dpi=300, bbox_inches="tight"
            )
        plt.close(fig)


def plot_tariff_findings(table, output):
    """Matched level/timing comparison, showing utilisation and both cost accounts.

    Requires the named controls from tariff_findings_30mw.yaml. The hourly family
    and gain are declared before the solves; this plot does not select a winner.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    selected = ["reference", "constant_5", "hourly_5_g025", "hourly_5_g1"]
    labels = ["Monthly\nreference", "Constant\n5", "Hourly\ngain 0.25", "Hourly\ngain 1"]
    scenarios = list(table.scenario.unique())
    table = table.copy()
    table["displayed_corrective_gap_bound_dkk"] = table.combined_system_solver_gap_bound_dkk
    # A reference compared with itself has exactly zero difference: the same
    # incumbent/bound uncertainty cancels, rather than adding two independent gaps.
    table.loc[table.tariff == "reference", "displayed_corrective_gap_bound_dkk"] = 0.0
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with plt.rc_context(
        {
            "font.size": 9,
            "pdf.fonttype": 42,
            "svg.fonttype": "none",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    ):
        fig, axes = plt.subplots(
            len(scenarios),
            3,
            figsize=(10.5, 2.6 * len(scenarios)),
            squeeze=False,
            layout="constrained",
        )
        for row, scenario in enumerate(scenarios):
            data = table.loc[table.scenario == scenario].set_index("tariff").loc[selected]
            x = np.arange(len(selected))
            a, b, c = axes[row]
            colors = ["#999999", COLORS[0], COLORS[2], COLORS[3]]
            a.bar(x, data.ptes_discharge_mwh, color=colors)
            period = scenario.split("__", 1)[0].capitalize()
            a.set_ylabel(period + "\nDischarge [MWh]")
            b.bar(
                x - 0.18,
                data.local_bill_saving_dkk / 1000,
                width=0.36,
                color=COLORS[0],
                label="HTF bill saving",
            )
            b.bar(
                x + 0.18,
                data.aggregate_upstream_operating_surplus_change_dkk / 1000,
                width=0.36,
                color=COLORS[1],
                label="Upstream aggregate gain",
            )
            b.set_ylabel("Benefit [thousand DKK]")
            c.bar(x, data.system_operating_cost_saving_dkk / 1000, color=colors)
            c.errorbar(
                x,
                data.system_operating_cost_saving_dkk / 1000,
                yerr=data.displayed_corrective_gap_bound_dkk / 1000,
                fmt="none",
                color="black",
                capsize=3,
            )
            c.set_ylabel("Operating saving [thousand DKK]")
            for ax in (a, b, c):
                ax.axhline(0, color="black", lw=0.7)
                ax.set_xticks(x, labels, fontsize=8)
                ax.grid(axis="y", alpha=0.18)
                ax.set_axisbelow(True)
            if row == 0:
                a.set_title("PTES utilisation")
                b.set_title("Distribution of benefits")
                b.legend(fontsize=7, loc="lower left", bbox_to_anchor=(0, 1.1))
                c.set_title("System operating benefit")
        fig.suptitle(
            "2024 representative weeks · 30 MW charging/discharging\n"
            "Hourly discount: 0–10 DKK/MWh, mean 5; assumed pumping: 0.005 per flow",
            fontsize=11,
        )
        for extension in ["pdf", "svg", "png"]:
            fig.savefig(output / f"tariff_findings.{extension}", dpi=300, bbox_inches="tight")
        table.to_csv(output / "figure_source_data.csv", index=False)
        plt.close(fig)
