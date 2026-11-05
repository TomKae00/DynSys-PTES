"""Prepare data, solve PyPSA dispatch or compare local tariffs with upstream adjustment."""

import argparse
import hashlib
import json
import logging
import platform
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import highspy
import linopy
import numpy as np
import pandas as pd
import pypsa
import xarray as xr
import yaml

from .data import demo, prepare
from .optimisation import build, solve
from .workflow import compare


def _write_outputs(output, solutions, *, provenance, plants_hash, comparison=None):
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory already contains results; choose an empty directory")
    runtime = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "pypsa": pypsa.__version__,
        "linopy": linopy.__version__,
        "xarray": xr.__version__,
        "highs": highspy.Highs().version(),
    }
    with TemporaryDirectory(prefix=".cph-", dir=output.parent) as temporary:
        staging = Path(temporary)
        for label, solution in solutions.items():
            folder = staging / label if comparison is not None else staging
            folder.mkdir(exist_ok=True)
            solution.summary.update(
                {
                    "input_provenance": provenance,
                    "runtime": runtime,
                    "plant_input_sha256": plants_hash,
                    "case": label,
                    "start_utc": str(solution.dispatch.index[0]),
                    "end_utc": str(solution.dispatch.index[-1]),
                }
            )
            solution.network.meta.update(
                {
                    "case": label,
                    "runtime": runtime,
                    "input_provenance": provenance,
                    "plant_input_sha256": plants_hash,
                }
            )
            solution.network.export_to_netcdf(folder / "network.nc")
            solution.dispatch.to_csv(folder / "dispatch.csv", index_label="timestamp")
            (folder / "summary.json").write_text(
                json.dumps(solution.summary, indent=2, allow_nan=False)
            )
        if comparison is not None:
            (staging / "comparison.json").write_text(
                json.dumps(comparison, indent=2, allow_nan=False)
            )
        if output.exists():
            output.rmdir()  # empty only; an intervening write fails safely
        staging.rename(output)


def _run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "solve", "demo", "compare"])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--repair", action="store_true")
    parser.add_argument(
        "--synthetic", action="store_true", help="Explicit synthetic input for comparison demos"
    )
    parser.add_argument("--hours", type=int, help="Explicit diagnostic horizon")
    parser.add_argument("--start", help="UTC start timestamp for a diagnostic window")
    parser.add_argument(
        "--relax", action="store_true", help="Diagnostic LP relaxation of operating modes"
    )
    parser.add_argument("--objective", choices=["system", "local"])
    parser.add_argument("--hp-policy", choices=["endogenous", "must_run"])
    parser.add_argument("--charging-policy", choices=["fixed", "curtailable"])
    parser.add_argument("--time-limit", type=float, help="Time limit per solver call, in seconds")
    parser.add_argument("--mip-gap", type=float)
    parser.add_argument("--solver", choices=["highs", "gurobi"])
    parser.add_argument("--discount", type=float, help="Supplied discharge credit, DKK/MWh")
    parser.add_argument(
        "--schedule", type=Path, help="Central dispatch.csv with the charging schedule"
    )
    parser.add_argument("--prices", action="store_true", help="Fixed-commitment LP marginal values")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.getLogger("pypsa").setLevel(logging.INFO if args.verbose else logging.WARNING)
    logging.getLogger("linopy").setLevel(logging.INFO if args.verbose else logging.WARNING)
    if args.command == "prepare":
        frame, report = prepare(args.root, args.year, repair=args.repair)
        print(json.dumps({"hours": len(frame), "repaired_cells": len(report["repairs"])}))
        return
    config = yaml.safe_load((args.config or args.root / "config/base.yaml").read_text())
    config["year"] = args.year
    config.setdefault("response", {"charging_policy": "curtailable"})
    if args.relax:
        config["integer_operation"] = False
    for value, group, key in [
        (args.objective, config, "objective"),
        (args.hp_policy, config["heat_pumps"], "policy"),
        (args.charging_policy, config["response"], "charging_policy"),
        (args.solver, config["solver"], "backend"),
    ]:
        if value is not None:
            group[key] = value
    if args.time_limit is not None:
        if args.time_limit <= 0:
            raise ValueError("Time limit must be positive")
        config["solver"]["time_limit"] = args.time_limit
    if args.mip_gap is not None:
        if not 0 <= args.mip_gap < 1:
            raise ValueError("MILP gap must be in [0,1)")
        config["solver"]["mip_rel_gap"] = args.mip_gap
    synthetic = args.command == "demo" or args.synthetic
    if synthetic:
        frame = demo(args.hours or 168)
        provenance = {"kind": "synthetic_demo"}
    else:
        path = args.inputs or args.root / f"data/processed/inputs_{args.year}.csv"
        frame = pd.read_csv(path, index_col=0)
        frame.index = pd.to_datetime(frame.index, utc=True)
        provenance = {
            "kind": "prepared_inputs",
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    if args.start:
        start = pd.Timestamp(args.start)
        start = start.tz_localize("UTC") if start.tz is None else start.tz_convert("UTC")
        frame = frame.loc[frame.index >= start]
        if frame.empty or frame.index[0] != start:
            raise ValueError("Start is not a covered hourly timestamp")
    if args.hours:
        if not 2 <= args.hours <= len(frame):
            raise ValueError(
                "Requested horizon must be at least two hours and within input coverage"
            )
        frame = frame.iloc[: args.hours]
    if args.discount is not None:
        config["discharge_discount_dkk_mwh"] = args.discount
        frame["discharge_discount_dkk_mwh"] = args.discount
    if args.schedule:
        scheduled = pd.read_csv(args.schedule, index_col=0)
        scheduled.index = pd.to_datetime(scheduled.index, utc=True)
        if scheduled.index.has_duplicates:
            raise ValueError("Duplicate schedule timestamps")
        frame["scheduled_ptes_charge_mw"] = scheduled.ptes_charge_mw.reindex(frame.index)
        provenance["schedule_sha256"] = hashlib.sha256(args.schedule.read_bytes()).hexdigest()
    path = args.root / "config/plants.csv"
    plants = pd.read_csv(path)
    output = args.output or args.root / "results" / args.command
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory already contains results; choose an empty directory")
    if args.command == "compare":
        if args.discount is None and "discharge_discount_dkk_mwh" not in frame:
            raise ValueError("Supply --discount or an hourly discharge_discount_dkk_mwh column")
        discount = frame.get("discharge_discount_dkk_mwh", args.discount)
        solutions, comparison = compare(
            frame, config, plants, discount=discount, prices=args.prices
        )
        _write_outputs(
            output,
            solutions,
            provenance=provenance,
            plants_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            comparison=comparison,
        )
        print(json.dumps(comparison, indent=2))
    else:
        solution = solve(build(frame, config, plants), prices=args.prices)
        _write_outputs(
            output,
            {"dispatch": solution},
            provenance=provenance,
            plants_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        print(
            json.dumps(
                {
                    k: solution.summary[k]
                    for k in [
                        "framework",
                        "objective_kind",
                        "objective_dkk",
                        "hours",
                        "solver_status",
                        "mip_gap",
                        "ptes_equivalent_cycles",
                        "max_constraint_violation",
                    ]
                },
                indent=2,
            )
        )


def main(argv=None):
    try:
        _run(argv)
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
