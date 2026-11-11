"""One announced schedule, two tariff responses and corrective upstream PyPSA solves."""

from copy import deepcopy

import numpy as np

from .optimisation import _optimise, build, feasibility, solve
from .results import _solver_info


def coordinated(frame, config, plants, *, prices=False):
    """One tariff-independent announced schedule for a matched physical scenario."""
    if config["settlement_boundary"] != "discharge_service":
        raise ValueError("Coupled tariff comparison requires the discharge-service boundary")
    central_config = deepcopy(config)
    central_config["objective"] = "system"
    central_config["discharge_discount_dkk_mwh"] = 0.0
    central_inputs = frame.drop(columns=["discharge_discount_dkk_mwh"], errors="ignore")
    central = solve(build(central_inputs, central_config, plants), prices=prices)
    return central


def response(frame, config, plants, central, credit, *, direct_tariff=None, follow_schedule=False):
    """Local response and physical correction, keeping all actual local decisions fixed.

    With follow_schedule, HTF implements the coordinated PTES charging and discharge
    exactly and only chooses heat-exchanger import and local heat pumps."""
    inputs = frame.copy()
    inputs["scheduled_ptes_charge_mw"] = central.dispatch.ptes_charge_mw
    inputs["scheduled_ptes_discharge_mw"] = central.dispatch.ptes_discharge_mw
    if follow_schedule:
        config = deepcopy(config)
        config.setdefault("response", {}).update(charging_policy="fixed", discharge_policy="fixed")
    inputs["discharge_discount_dkk_mwh"] = credit
    if direct_tariff is not None:
        inputs["reference_tariff_dkk_mwh"] = direct_tariff
    if not np.isfinite(inputs.discharge_discount_dkk_mwh).all():
        raise ValueError("Tariff discount must cover every snapshot")
    local_config = deepcopy(config)
    local_config["objective"] = "local"
    local_config["solver"]["mip_rel_gap"] = config.get("response", {}).get(
        "local_mip_rel_gap", config["solver"]["mip_rel_gap"]
    )
    if np.isscalar(credit):
        local_config["discharge_discount_dkk_mwh"] = float(credit)
    local = solve(build(inputs, local_config, plants))
    system_config = deepcopy(config)
    system_config["objective"] = "system"
    corrective, tolerance = _corrective(inputs, system_config, plants, local)
    for column in ["hx_mw", "ptes_discharge_mw", "city2_heat_mw", "groundwater_heat_mw"]:
        if not np.allclose(
            local.dispatch[column], corrective.dispatch[column], atol=max(1e-5, 2 * tolerance)
        ):
            raise RuntimeError("Corrective solve changed an actual local decision")
    return local, corrective


RETRY_TOLERANCE_MW = 1e-3


def _corrective(inputs, system_config, plants, local):
    """Upstream re-dispatch with HTF's decisions fixed; one retry with a narrow band.

    Fixing values from another solve exactly can sit on a solver tolerance limit and be
    reported infeasible; the retry keeps them within RETRY_TOLERANCE_MW instead.
    """
    try:
        return solve(build(inputs, system_config, plants, fixed_local=local.dispatch)), 0.0
    except RuntimeError:
        network = build(
            inputs,
            system_config,
            plants,
            fixed_local=local.dispatch,
            fixed_tolerance=RETRY_TOLERANCE_MW,
        )
        return solve(network), RETRY_TOLERANCE_MW


def historical(frame, config, plants):
    """Measured operation: PTES flows fixed to meters; HTF chooses HX and HPs under
    the monthly tariff; upstream is re-dispatched around it. No design limits,
    operating rules or terminal inventory apply to the replayed PTES."""
    inputs = frame.copy()
    inputs["scheduled_ptes_charge_mw"] = inputs.metered_charge_mw
    inputs["discharge_discount_dkk_mwh"] = 0.0
    replay = deepcopy(config)
    replay["ptes"]["replay_metered"] = True
    replay.setdefault("response", {})["charging_policy"] = "fixed"
    replay["discharge_discount_dkk_mwh"] = 0.0
    local_config = deepcopy(replay)
    local_config["objective"] = "local"
    local_config["solver"]["mip_rel_gap"] = replay["response"].get(
        "local_mip_rel_gap", replay["solver"]["mip_rel_gap"]
    )
    local = solve(build(inputs, local_config, plants))
    system_config = deepcopy(replay)
    system_config["objective"] = "system"
    corrective, _ = _corrective(inputs, system_config, plants, local)
    return local, corrective


def case_metrics(central, local, corrective):
    actual = corrective.dispatch
    return {
        "local_expenditure_dkk": local.summary["illustrative_settlement"]["local_expenditure_dkk"],
        "supplier_local_heat_revenue_dkk": local.summary["illustrative_settlement"][
            "supplier_local_heat_revenue_dkk"
        ],
        "local_real_cost_dkk": local.summary["illustrative_settlement"][
            "local_electricity_and_startup_dkk"
        ],
        "corrective_system_cost_dkk": corrective.summary["objective_dkk"],
        "system_cost_change_from_coordinated_dkk": corrective.summary["objective_dkk"]
        - central.summary["objective_dkk"],
        "system_solver_gap_dkk": corrective.summary["absolute_optimality_gap_dkk"],
        "local_solver_gap_dkk": local.summary["absolute_optimality_gap_dkk"],
        "ptes_charge_mwh": float(actual.ptes_charge_mw.sum()),
        "ptes_discharge_mwh": float(actual.ptes_discharge_mw.sum()),
        "ptes_equivalent_discharge_cycles": float(
            actual.ptes_discharge_mw.sum() / corrective.summary["assumptions"]["ptes"]["energy_mwh"]
        ),
        "charging_curtailed_mwh": float(
            (central.dispatch.ptes_charge_mw - actual.ptes_charge_mw).sum()
        ),
        "missed_scheduled_discharge_mwh": float(
            (central.dispatch.ptes_discharge_mw - actual.ptes_discharge_mw).clip(lower=0).sum()
        ),
        "ptes_terminal_mwh": float(actual.ptes_energy_mwh.iloc[-1]),
        "ptes_standing_loss_mwh": float(actual.ptes_standing_loss_mwh.sum()),
    }


def benefits(reference, candidate):
    """Transfers cancel: local saving + aggregate upstream surplus = operating saving.

    The aggregate is a hypothetical consolidated account, not VEKS/producer profit.
    """
    saving = reference["corrective_system_cost_dkk"] - candidate["corrective_system_cost_dkk"]
    local = reference["local_expenditure_dkk"] - candidate["local_expenditure_dkk"]
    revenue = (
        candidate["supplier_local_heat_revenue_dkk"] - reference["supplier_local_heat_revenue_dkk"]
    )
    upstream = (
        saving + revenue + candidate["local_real_cost_dkk"] - reference["local_real_cost_dkk"]
    )
    gap = reference["system_solver_gap_dkk"] + candidate["system_solver_gap_dkk"]
    return {
        "system_operating_cost_saving_dkk": saving,
        "local_bill_saving_dkk": local,
        "supplier_local_heat_revenue_change_dkk": revenue,
        "aggregate_upstream_operating_surplus_change_dkk": upstream,
        "stakeholder_reconciliation_residual_dkk": local + upstream - saving,
        "combined_system_solver_gap_bound_dkk": gap,
        "system_saving_lower_bound_dkk": saving - gap,
        "system_saving_upper_bound_dkk": saving + gap,
        "system_difference_exceeds_gap_bound": bool(abs(saving) > gap),
    }


def local_discharge_range(local, *, tolerance_dkk=0.01):
    """Two secondary optimisations bound throughput within a declared expenditure band.

    No tie-breaking cost is introduced in the main model. Integer restrictions and
    announced charging remain active; extrema need not be pointwise hourly bounds.
    """
    if local.summary["objective_kind"] != "local" or tolerance_dkk < 0:
        raise ValueError("Discharge-range diagnostic needs a local solve and nonnegative tolerance")
    results = {}
    for label, sign in [("minimum", 1), ("maximum", -1)]:
        n = build(local.network._cph_inputs, local.network._cph_config, local.network._cph_plants)

        def secondary(network):
            m = network.model
            primary = m.objective.expression
            m.add_constraints(
                primary <= local.summary["objective_dkk"] + tolerance_dkk,
                name="near_optimal_htf_expenditure",
            )
            total = (
                m["Link-p"].sel(name="ptes_discharge").sum()
                * n._cph_config["ptes"]["discharge_efficiency"]
            )
            m.add_objective(sign * total, overwrite=True)

        _optimise(n, model_callback=secondary)
        feasibility(n)
        results[label + "_mwh"] = float(n.links_t.p1.ptes_discharge.sum() * -1)
        # The solver-info helper's numeric gap has the current objective's units:
        # here MWh rather than DKK, because this is a secondary throughput solve.
        results[label + "_solver_gap_mwh"] = _solver_info(n)["absolute_optimality_gap_dkk"]
    results["expenditure_band_dkk"] = tolerance_dkk
    results["primary_solver_gap_dkk"] = local.summary["absolute_optimality_gap_dkk"]
    results["interpretation"] = (
        "Extrema within accepted HTF expenditure plus tolerance; not predicted behaviour or hourly bounds"
    )
    return results


def compare(frame, config, plants, *, discount, prices=False, response_range=False):
    central = coordinated(frame, config, plants, prices=prices)
    solutions = {"central": central}
    metrics = {
        "framework": "PyPSA",
        "charging_policy": config.get("response", {}).get("charging_policy", "curtailable"),
        "coordinated_objective_dkk": central.summary["objective_dkk"],
        "cases": {},
    }
    for label, credit in [("reference", 0.0), ("candidate", discount)]:
        local, corrective = response(frame, config, plants, central, credit)
        solutions[label + "_local"] = local
        solutions[label + "_corrective"] = corrective
        metrics["cases"][label] = case_metrics(central, local, corrective)
    reference, candidate = metrics["cases"]["reference"], metrics["cases"]["candidate"]
    metrics["candidate_vs_reference"] = benefits(reference, candidate)
    if response_range:
        metrics["reference_near_optimal_discharge_range"] = local_discharge_range(
            solutions["reference_local"]
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
