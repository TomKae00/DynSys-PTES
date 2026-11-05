"""One announced schedule, two tariff responses and corrective upstream PyPSA solves."""

from copy import deepcopy

import numpy as np

from .optimisation import build, solve


def compare(frame, config, plants, *, discount, prices=False):
    if config["settlement_boundary"] != "discharge_service":
        raise ValueError("Coupled tariff comparison requires the discharge-service boundary")
    central_config = deepcopy(config)
    central_config["objective"] = "system"
    central_config["discharge_discount_dkk_mwh"] = 0.0
    central_inputs = frame.drop(columns=["discharge_discount_dkk_mwh"], errors="ignore")
    central = solve(build(central_inputs, central_config, plants), prices=prices)
    announced = frame.copy()
    announced["scheduled_ptes_charge_mw"] = central.dispatch.ptes_charge_mw
    solutions = {"central": central}
    metrics = {
        "framework": "PyPSA",
        "charging_policy": config.get("response", {}).get("charging_policy", "curtailable"),
        "coordinated_objective_dkk": central.summary["objective_dkk"],
        "cases": {},
    }
    for label, credit in [("reference", 0.0), ("candidate", discount)]:
        inputs = announced.copy()
        inputs["discharge_discount_dkk_mwh"] = credit
        if not np.isfinite(inputs.discharge_discount_dkk_mwh).all():
            raise ValueError("Tariff discount must cover every snapshot")
        local_config = deepcopy(config)
        local_config["objective"] = "local"
        if np.isscalar(credit):
            local_config["discharge_discount_dkk_mwh"] = float(credit)
        local = solve(build(inputs, local_config, plants))
        corrective = solve(build(inputs, central_config, plants, fixed_local=local.dispatch))
        for column in ["hx_mw", "ptes_discharge_mw", "city2_heat_mw", "groundwater_heat_mw"]:
            if not np.allclose(local.dispatch[column], corrective.dispatch[column], atol=1e-5):
                raise RuntimeError("Corrective solve changed an actual local decision")
        solutions[label + "_local"] = local
        solutions[label + "_corrective"] = corrective
        actual = corrective.dispatch
        metrics["cases"][label] = {
            "local_expenditure_dkk": local.summary["illustrative_settlement"][
                "local_expenditure_dkk"
            ],
            "supplier_local_heat_revenue_dkk": local.summary["illustrative_settlement"][
                "supplier_local_heat_revenue_dkk"
            ],
            "corrective_system_cost_dkk": corrective.summary["objective_dkk"],
            "system_cost_change_from_coordinated_dkk": corrective.summary["objective_dkk"]
            - central.summary["objective_dkk"],
            "ptes_charge_mwh": float(actual.ptes_charge_mw.sum()),
            "ptes_discharge_mwh": float(actual.ptes_discharge_mw.sum()),
            "charging_curtailed_mwh": float(
                (announced.scheduled_ptes_charge_mw - actual.ptes_charge_mw).sum()
            ),
            "missed_scheduled_discharge_mwh": float(
                (central.dispatch.ptes_discharge_mw - actual.ptes_discharge_mw).clip(lower=0).sum()
            ),
            "ptes_terminal_mwh": float(actual.ptes_energy_mwh.iloc[-1]),
        }
    reference, candidate = metrics["cases"]["reference"], metrics["cases"]["candidate"]
    metrics["candidate_vs_reference"] = {
        "system_operating_cost_saving_dkk": reference["corrective_system_cost_dkk"]
        - candidate["corrective_system_cost_dkk"],
        "local_bill_saving_dkk": reference["local_expenditure_dkk"]
        - candidate["local_expenditure_dkk"],
        "supplier_local_heat_revenue_change_dkk": candidate["supplier_local_heat_revenue_dkk"]
        - reference["supplier_local_heat_revenue_dkk"],
    }
    gap_bound = sum(
        solutions[k + "_corrective"].summary["absolute_optimality_gap_dkk"]
        for k in ["reference", "candidate"]
    )
    metrics["candidate_vs_reference"]["combined_system_solver_gap_bound_dkk"] = gap_bound
    metrics["candidate_vs_reference"]["system_difference_exceeds_gap_bound"] = bool(
        abs(metrics["candidate_vs_reference"]["system_operating_cost_saving_dkk"]) > gap_bound
    )
    metrics["limitations"] = [
        "One-pass rational response benchmark; not a behavioural or market-equilibrium model",
        "Corrective electricity is valued at the same exogenous DK2 prices; no balancing-market settlement",
        "Candidate discount is supplied, not an optimally derived tariff",
        "Curtailable charging assumes upstream adaptation within the announced charging ceiling",
        "Reference can be economically indifferent when pumping is zero and tariffs are equal",
        "Supplier local heat revenue is not supplier profit; imbalance/deviation charges are not included",
    ]
    return solutions, metrics
