"""Prepare data, solve PyPSA dispatch or compare local tariffs with upstream adjustment."""

import argparse
import hashlib
import json
import logging
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory

import highspy
import linopy
import numpy as np
import pandas as pd
import pypsa
import xarray as xr
import yaml

from .data import demo, prepare, year_index
from .optimisation import build, solve
from .profiles import build_profiles, hourly_series, read_era5
from .study import evaluate_tariffs, study_cases
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
        "source_sha256": hashlib.sha256(
            b"".join(
                p.name.encode() + p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py"))
            )
        ).hexdigest(),
    }
    try:
        runtime["gurobi"] = version("gurobipy")
    except PackageNotFoundError:
        pass
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
            solution.network._cph_inputs.to_csv(folder / "inputs.csv", index_label="timestamp")
            solution.network._cph_plants.to_csv(folder / "plants.csv", index=False)
            solution.summary["case_inputs_sha256"] = hashlib.sha256(
                (folder / "inputs.csv").read_bytes()
            ).hexdigest()
            solution.summary["archived_plants_sha256"] = hashlib.sha256(
                (folder / "plants.csv").read_bytes()
            ).hexdigest()
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
    parser.add_argument(
        "command",
        choices=[
            "prepare",
            "profiles",
            "metered",
            "solve",
            "demo",
            "compare",
            "study",
            "rolling",
            "report",
        ],
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--local-profiles", type=Path, help="Timestamped UTC temperature/COP CSV")
    weather = parser.add_mutually_exclusive_group()
    weather.add_argument(
        "--ambient-csv", type=Path, help="UTC time,temperature_c input including warm-up"
    )
    weather.add_argument(
        "--era5-files", type=Path, nargs="+", help="Existing ERA5-Land NetCDF files"
    )
    parser.add_argument(
        "--study-spec", type=Path, help="YAML periods, sensitivities and tariff candidates"
    )
    parser.add_argument(
        "--figures", action="store_true", help="Include tariff-response figures in a study"
    )
    parser.add_argument("--run", type=Path, help="Accepted result folder for report")
    parser.add_argument("--observations", type=Path, help="Recorded hourly PTES CSV for context")
    parser.add_argument("--observation-kind", choices=["soc_proxy", "metered"])
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
    parser.add_argument(
        "--response-range",
        action="store_true",
        help="Two extra solves bound near-optimal reference throughput",
    )
    parser.add_argument(
        "--raw-ptes",
        type=Path,
        help="10-minute PTES operation CSV with metered E_charge/E_discharge",
    )
    parser.add_argument(
        "--metered", type=Path, help="Hourly metered PTES CSV from the 'metered' command"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.getLogger("pypsa").setLevel(logging.INFO if args.verbose else logging.WARNING)
    logging.getLogger("linopy").setLevel(logging.INFO if args.verbose else logging.WARNING)
    if args.command == "profiles":
        sources = args.era5_files or ([args.ambient_csv] if args.ambient_csv else [])
        if not sources:
            raise ValueError(
                "Profiles require --ambient-csv or --era5-files; no implicit downloads"
            )
        if args.ambient_csv:
            source = pd.read_csv(args.ambient_csv, index_col="time").temperature_c
            ambient = hourly_series(source)
        else:
            ambient = read_era5(args.era5_files)
        profiles = build_profiles(ambient, year_index(args.year))
        output = args.output or args.root / f"data/processed/profiles_{args.year}"
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and any(output.iterdir()):
            raise ValueError("Profiles output must be empty")
        with TemporaryDirectory(prefix=".profiles-", dir=output.parent) as temporary:
            staging = Path(temporary)
            profiles.to_csv(staging / "local_profiles.csv")
            (staging / "provenance.json").write_text(
                json.dumps(
                    {
                        "method": "Historical HTF netpoint curves, 24h ambient average, 50C return, Lorenz approximation",
                        "timezone": "UTC",
                        "model_year_timezone": "Europe/Copenhagen",
                        "profile_source_sha256": hashlib.sha256(
                            (Path(__file__).parent / "profiles.py").read_bytes()
                        ).hexdigest(),
                        "sources": {
                            str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sources
                        },
                        "warning": "Modelled temperatures and COPs; not measured HTF operating profiles",
                    },
                    indent=2,
                )
            )
            if output.exists():
                output.rmdir()
            staging.rename(output)
        print(json.dumps({"hours": len(profiles), "output": str(output)}))
        return
    if args.command == "prepare":
        frame, report = prepare(
            args.root, args.year, repair=args.repair, local_profiles=args.local_profiles
        )
        print(json.dumps({"hours": len(frame), "repaired_cells": len(report["repairs"])}))
        return
    if args.command == "metered":
        from .observations import metered_ptes

        if args.raw_ptes is None or args.observations is None:
            raise ValueError(
                "Metered requires --raw-ptes and --observations (hourly inventory CSV)"
            )
        metered = metered_ptes(args.raw_ptes, args.observations)
        output = args.output or args.root / f"data/processed/ptes_metered_{args.year}.csv"
        if output.exists():
            raise ValueError("Metered output already exists; choose a new path")
        output.parent.mkdir(parents=True, exist_ok=True)
        metered.to_csv(output)
        print(
            json.dumps(
                {
                    "hours": len(metered),
                    "charge_mwh": round(float(metered.metered_charge_mw.sum()), 1),
                    "discharge_mwh": round(float(metered.metered_discharge_mw.sum()), 1),
                    "output": str(output),
                }
            )
        )
        return
    if args.command == "report":
        from .plotting import report

        if args.run is None:
            raise ValueError("Report requires --run pointing to an accepted result folder")
        # Prefer the plant inputs archived with new exports.
        plant_path = args.run / "plants.csv"
        if not plant_path.exists():
            plant_path = args.run / "central/plants.csv"
        if not plant_path.exists():
            plant_path = args.root / "config/plants.csv"
        report(
            args.run,
            args.output or args.run / "figures",
            pd.read_csv(plant_path),
            observations=args.observations,
            observation_kind=args.observation_kind,
        )
        print(json.dumps({"figures": str(args.output or args.run / "figures")}))
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
    if args.local_profiles is not None:
        from .profiles import apply_profiles

        frame = apply_profiles(frame, args.local_profiles)
        provenance["local_profiles_sha256"] = hashlib.sha256(
            args.local_profiles.read_bytes()
        ).hexdigest()
        profile_provenance = args.local_profiles.with_name("provenance.json")
        if profile_provenance.exists():
            provenance["local_profile_generation"] = json.loads(profile_provenance.read_text())
    if args.metered is not None:
        metered = pd.read_csv(args.metered, index_col=0)
        metered.index = pd.to_datetime(metered.index, utc=True)
        columns = ["metered_charge_mw", "metered_discharge_mw", "measured_inventory_mwh"]
        frame = frame.join(metered[columns])
        provenance["metered_ptes_sha256"] = hashlib.sha256(args.metered.read_bytes()).hexdigest()
    provenance["command_arguments"] = list(argv) if argv is not None else sys.argv[1:]
    quality_path = args.root / f"data/processed/quality_{args.year}.json"
    if not synthetic and args.inputs is None and quality_path.exists():
        provenance["preparation_report"] = json.loads(quality_path.read_text())
    path = args.root / "config/plants.csv"
    plants = pd.read_csv(path)
    output = args.output or args.root / "results" / args.command
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory already contains results; choose an empty directory")
    if args.command == "rolling":
        if args.study_spec is None:
            raise ValueError("Rolling requires --study-spec")
        _rolling(args, frame, config, plants, output, provenance)
        return
    if args.command == "study":
        if args.study_spec is None:
            raise ValueError("Study requires --study-spec")
        spec = yaml.safe_load(args.study_spec.read_text())
        provenance["study_spec_sha256"] = hashlib.sha256(args.study_spec.read_bytes()).hexdigest()
        output.parent.mkdir(parents=True, exist_ok=True)
        rows, reports = [], {}
        with TemporaryDirectory(prefix=".study-", dir=output.parent) as temporary:
            staging = Path(temporary)
            for name, inputs, settings in study_cases(frame, config, spec):
                solutions, metrics, table = evaluate_tariffs(
                    inputs, settings, plants, spec["tariffs"]
                )
                _write_outputs(
                    staging / name,
                    solutions,
                    provenance=provenance,
                    plants_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                    comparison=metrics,
                )
                table.insert(0, "scenario", name)
                rows.append(table)
                reports[name] = {k: v for k, v in metrics.items() if k != "cases"}
                print(
                    json.dumps(
                        {"scenario": name, "best_tested_tariff": metrics["best_tested_tariff"]}
                    )
                )
            if not rows:
                raise ValueError("Study must contain at least one period and sensitivity")
            combined = pd.concat(rows, ignore_index=True)
            combined.to_csv(staging / "study.csv", index=False)
            (staging / "study.json").write_text(
                json.dumps(
                    {"specification": spec, "scenarios": reports, "provenance": provenance},
                    indent=2,
                    allow_nan=False,
                )
            )
            if args.figures:
                from .plotting import plot_study

                plot_study(combined, staging)
            if output.exists():
                output.rmdir()
            staging.rename(output)
    elif args.command == "compare":
        if args.discount is None and "discharge_discount_dkk_mwh" not in frame:
            raise ValueError("Supply --discount or an hourly discharge_discount_dkk_mwh column")
        discount = frame.get("discharge_discount_dkk_mwh", args.discount)
        solutions, comparison = compare(
            frame,
            config,
            plants,
            discount=discount,
            prices=args.prices,
            response_range=args.response_range,
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


def _rolling(args, frame, config, plants, output, provenance):
    """Daily rolling-horizon study: reference, coordinated schedule and tariff cases."""
    from .rolling import COORDINATED, REFERENCE, run_case, summarise
    from .study import update_config

    spec = yaml.safe_load(args.study_spec.read_text())
    provenance["study_spec_sha256"] = hashlib.sha256(args.study_spec.read_bytes()).hexdigest()
    start = pd.Timestamp(spec["period"]["start"])
    if start.tzinfo is None:
        raise ValueError("Rolling period start must include a timezone")
    snapshots = pd.date_range(start.tz_convert("UTC"), periods=int(spec["period"]["hours"]), freq="h")
    if not snapshots.isin(frame.index).all():
        raise ValueError("Rolling period is outside the complete input horizon")
    inputs = frame.loc[snapshots].copy()
    settings = update_config(config, spec.get("overrides", {}))
    rolling = spec.get("rolling", {})
    cases = [(REFERENCE, None), (COORDINATED, None)] + [(t["name"], t) for t in spec["tariffs"]]
    output.parent.mkdir(parents=True, exist_ok=True)

    def progress(case, timestamp):
        if timestamp.dayofweek == 0 and timestamp.hour == 0:
            print(json.dumps({"case": case, "day": str(timestamp.date())}), flush=True)

    results = {}
    with TemporaryDirectory(prefix=".rolling-", dir=output.parent) as temporary:
        staging = Path(temporary)
        for name, tariff in cases:
            realized, plans = run_case(
                inputs, settings, plants, name, rolling=rolling, spec=tariff, progress=progress
            )
            folder = staging / name
            folder.mkdir()
            realized.to_csv(folder / "dispatch.csv", index_label="timestamp")
            if not plans.empty:
                plans.to_csv(folder / "plans.csv", index=False)
            results[name] = realized
        table = summarise(results, settings)
        table.to_csv(staging / "rolling.csv", index=False)
        (staging / "rolling.json").write_text(
            json.dumps(
                {
                    "specification": spec,
                    "coordination_value_dkk": table.attrs["coordination_value_dkk"],
                    "terminal_value_dkk_mwh": table.attrs["terminal_value_dkk_mwh"],
                    "provenance": provenance,
                },
                indent=2,
                default=str,
            )
        )
        if output.exists():
            output.rmdir()
        staging.rename(output)
    print(table.to_string(index=False))
