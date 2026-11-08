"""Matched tariff sweeps with reusable coordinated/reference PyPSA solutions."""

import re
from copy import deepcopy

import numpy as np
import pandas as pd

from .tariffs import candidate_prices
from .workflow import benefits, case_metrics, coordinated, response


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
        raise ValueError("Case names must use letters, digits, underscores or hyphens")
    return value


def update_config(config, overrides):
    """Dotted paths only update existing parameters; spelling mistakes fail early."""
    result = deepcopy(config)
    for path, value in overrides.items():
        keys = path.split(".")
        target = result
        for key in keys[:-1]:
            if key not in target or not isinstance(target[key], dict):
                raise ValueError("Unknown sensitivity parameter: " + path)
            target = target[key]
        if keys[-1] not in target:
            # Explicit asymmetric PTES design sensitivities are optional parameters.
            if path not in ("ptes.charge_power_mw", "ptes.discharge_power_mw"):
                raise ValueError("Unknown sensitivity parameter: " + path)
        target[keys[-1]] = value
    return result


def study_cases(frame, config, specification):
    """Cross periods with labelled one-at-a-time or explicitly combined assumptions."""
    used = set()
    for period in specification["periods"]:
        start = pd.Timestamp(period["start"])
        if start.tzinfo is None:
            raise ValueError("Study period start must include a timezone")
        hours = int(period["hours"])
        snapshots = pd.date_range(start.tz_convert("UTC"), periods=hours, freq="h")
        if hours < 2 or not snapshots.isin(frame.index).all():
            raise ValueError("Study period is outside the complete input horizon")
        for sensitivity in specification.get("sensitivities", [{"name": "base"}]):
            name = identifier(period["name"]) + "__" + identifier(sensitivity["name"])
            if name in used:
                raise ValueError("Duplicate study case: " + name)
            used.add(name)
            yield (
                name,
                frame.loc[snapshots].copy(),
                update_config(config, sensitivity.get("overrides", {})),
            )


def evaluate_tariffs(frame, config, plants, specifications):
    """Choose within a declared finite family; retain all cases and uncertainty.

    This is an ex-post perfect-foresight scenario search, not a guaranteed optimal
    contract or an out-of-sample tariff evaluation.
    """
    names = [identifier(s["name"]) for s in specifications]
    if not names or len(set(names)) != len(names) or "reference" in names:
        raise ValueError("Supply unique tariff names, excluding reserved 'reference'")
    prices = any(
        s["family"] != "constant"
        or s.get("direct_basis", "monthly_reference") != "monthly_reference"
        for s in specifications
    )
    central = coordinated(frame, config, plants, prices=prices)
    local, corrective = response(frame, config, plants, central, 0.0)
    reference = case_metrics(central, local, corrective)
    solutions = {"central": central, "reference_local": local, "reference_corrective": corrective}
    rows = []
    # The zero-credit reference is itself eligible for selection.
    rows.append(
        {
            "tariff": "reference",
            "family": "constant",
            "level": 0.0,
            "scale": 0.0,
            "direct_basis": "monthly_reference",
            **reference,
            **benefits(reference, reference),
            "mean_credit_dkk_mwh": 0.0,
            "mean_direct_price_dkk_mwh": float(frame.reference_tariff_dkk_mwh.mean()),
            "mean_discharge_price_dkk_mwh": float(frame.reference_tariff_dkk_mwh.mean()),
        }
    )
    for spec in specifications:
        pricing = candidate_prices(central, spec)
        credit = pricing.discharge_discount_dkk_mwh
        local, corrective = response(
            frame, config, plants, central, credit, direct_tariff=pricing.reference_tariff_dkk_mwh
        )
        name = spec["name"]
        solutions[name + "_local"], solutions[name + "_corrective"] = local, corrective
        metrics = case_metrics(central, local, corrective)
        rows.append(
            {
                "tariff": name,
                "family": spec["family"],
                "direct_basis": spec.get("direct_basis", "monthly_reference"),
                "level": float(spec.get("level", 0)),
                "scale": float(spec.get("scale", 1)),
                **metrics,
                **benefits(reference, metrics),
                "mean_credit_dkk_mwh": float(credit.mean()),
                "mean_direct_price_dkk_mwh": float(pricing.reference_tariff_dkk_mwh.mean()),
                "mean_discharge_price_dkk_mwh": float(
                    pricing.discharge_service_price_dkk_mwh.mean()
                ),
                "minimum_credit_dkk_mwh": float(credit.min()),
                "maximum_credit_dkk_mwh": float(credit.max()),
            }
        )
    table = pd.DataFrame(rows).fillna(0.0)
    best = table.loc[table.corrective_system_cost_dkk.idxmin()]
    # Include alternatives whose cost intervals overlap the best accepted solution.
    near = (
        table.corrective_system_cost_dkk - table.system_solver_gap_dkk
        <= best.corrective_system_cost_dkk
    )
    # This consolidated-account screen cannot establish participation by each legal actor.
    table["aggregate_participation_screen"] = (table.local_bill_saving_dkk >= -1e-6) & (
        table.aggregate_upstream_operating_surplus_change_dkk >= -1e-6
    )
    if not np.isfinite(table.select_dtypes(include="number")).all().all():
        raise RuntimeError("Nonfinite study accounting")
    report = {
        "selection_criterion": "Lowest corrective system operating expenditure in the tested family, including reference",
        "best_tested_tariff": best.tariff,
        "best_aggregate_participating_tariff": table.loc[
            table.loc[table.aggregate_participation_screen, "corrective_system_cost_dkk"].idxmin(),
            "tariff",
        ],
        "solver_indistinguishable_tariffs": table.loc[near, "tariff"].tolist(),
        "tariff_specifications": specifications,
        "cases": table.to_dict(orient="records"),
        "limitations": [
            "Perfect-foresight in-sample candidate search, not a globally optimal contractual tariff",
            "Changing direct heat pricing also changes HP incentives and payment levels; isolate this from discharge-only pricing",
            "Arithmetic mean matching controls price level on sampled hours, not supplier revenue",
            "Conditional inventory duals can be nonunique under fixed modes and terminal endpoints",
            "Zero-pumping reference can have multiple equally optimal discharge responses",
            "Aggregate participation screen does not assign profit to VEKS, Varmelast or producers",
            "Operating savings include electricity adders and omit wider welfare/externalities",
        ],
    }
    return solutions, report, table
