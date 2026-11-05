"""Dispatch extraction and independent financial accounting for PyPSA results."""

from copy import deepcopy

import numpy as np


def collect(n):
    d = n._cph_inputs.copy()
    cfg = n._cph_config

    def power(name, port=1):
        values = getattr(n.links_t, "p" + str(port))[name].to_numpy()
        return values if port == 0 else -values

    d["hx_mw"] = power("hx")
    d["ptes_charge_mw"] = power("ptes_charge", 0) * n._cph_delivery
    d["ptes_discharge_mw"] = power("ptes_discharge")
    d["ptes_energy_mwh"] = n.stores_t.e.ptes.to_numpy()
    for mode in ["charge", "discharge"]:
        d["ptes_" + mode + "_on"] = n.model["ptes_" + mode + "_on"].solution.to_numpy()
        n.links_t.status["ptes_" + mode] = d["ptes_" + mode + "_on"].to_numpy()
    for name in ["city2", "groundwater"]:
        d[name + "_heat_mw"] = power(name)
        if cfg["heat_pumps"].get("policy", "endogenous") == "endogenous":
            d[name + "_on"] = n.links_t.status[name].to_numpy()
            d[name + "_start"] = n.links_t.start_up[name].to_numpy()
            d[name + "_stop"] = n.links_t.shut_down[name].to_numpy()
    d["local_hp_electricity_mw"] = power("city2", 0) + power("groundwater", 0)
    d["ptes_pump_electricity_mw"] = (d.ptes_charge_mw + d.ptes_discharge_mw) * cfg["ptes"][
        "pump_mwh_el_per_mwh_heat"
    ]
    d["electricity_market_net_mw"] = n.generators_t.p.electricity_market.to_numpy()
    if cfg["objective"] == "system":
        for p in n._cph_plants.itertuples():
            if p.kind == "backpressure":
                d[p.name + "_power_mw"] = power(p.name + "_chp")
                bypass = power(p.name + "_bypass") if p.name + "_bypass" in n.links.index else 0.0
                d[p.name + "_bypass_mw"] = bypass
                d[p.name + "_heat_mw"] = power(p.name + "_chp", 2) + bypass
            else:
                d[p.name + "_power_mw"] = power(p.name + "_power")
                d[p.name + "_heat_mw"] = power(p.name + "_heat")
            d[p.name + "_fuel_mw"] = n.generators_t.p[p.name + "_fuel"].to_numpy()
        for fuel in ["gas", "oil", "bio", "electric"]:
            d[fuel + "_boiler_heat_mw"] = power(fuel + "_boiler")
        d["regional_hp_heat_mw"] = power("regional_hp")
        d["waste_heat_mw"] = power("waste")
        for name in cfg["upstream"]["accumulators"]:
            d[name + "_charge_mw"] = power(name + "_charge", 0)
            d[name + "_discharge_mw"] = power(name + "_discharge")
            d[name + "_energy_mwh"] = n.stores_t.e[name].to_numpy()
    return d


def _solver_info(n):
    backend = n._cph_config["solver"].get("backend", "highs")
    solver = n.model.solver_model
    gap, bound = 0.0, float(n.objective)
    if backend == "highs":
        info = solver.getInfo()
        if np.isfinite(info.mip_gap):
            gap, bound = float(info.mip_gap), float(info.mip_dual_bound)
    elif solver.IsMIP:
        gap, bound = float(solver.MIPGap), float(solver.ObjBound)
    return {
        "solver_backend": backend,
        "solver_status": 0,
        "solver_message": n.model.termination_condition,
        "mip_gap": gap,
        "mip_dual_bound_dkk": bound,
        "absolute_optimality_gap_dkk": abs(n.objective - bound),
        "accepted_suboptimal": False,
    }


def summarise(n, d):
    cfg = n._cph_config
    hp, up = cfg["heat_pumps"], cfg["upstream"]
    owned = cfg["settlement_boundary"] == "legacy_owned_store"
    local_pump = (
        d.ptes_pump_electricity_mw
        if owned
        else d.ptes_discharge_mw * cfg["ptes"]["pump_mwh_el_per_mwh_heat"]
    )
    local_electricity = float(
        (
            (d.local_hp_electricity_mw + local_pump)
            * (d.electricity_dkk_mwh + hp["electricity_adder_dkk_mwh"])
        ).sum()
    )
    starts = sum(
        float(d[name + "_start"].sum() * hp[name]["capacity_mw"] * hp["startup_dkk_per_mw"])
        for name in ["city2", "groundwater"]
        if name + "_start" in d
    )
    discount = d.get("discharge_discount_dkk_mwh", cfg["discharge_discount_dkk_mwh"])
    billed = d.ptes_charge_mw if owned else d.ptes_discharge_mw
    purchase = float(((d.hx_mw + billed) * d.reference_tariff_dkk_mwh).sum())
    credit = float((d.ptes_discharge_mw * discount).sum())
    settlement = {
        "heat_purchase_dkk": purchase,
        "discharge_credit_dkk": credit,
        "supplier_local_heat_revenue_dkk": purchase - credit,
        "local_electricity_and_startup_dkk": local_electricity + starts,
        "local_expenditure_dkk": purchase - credit + local_electricity + starts,
    }
    contributions = {}
    for component, static, series, dispatch in [
        ("Generator", n.generators, n.generators_t, n.generators_t.p),
        ("Link", n.links, n.links_t, n.links_t.p0),
    ]:
        for name in static.index:
            cost = (
                series.marginal_cost[name]
                if name in series.marginal_cost
                else static.at[name, "marginal_cost"]
            )
            contributions[component + ":" + name] = float((dispatch[name] * cost).sum())
    contributions["HP startup costs"] = starts
    if not np.isclose(sum(contributions.values()), n.objective, rtol=1e-8, atol=1e-4):
        raise RuntimeError("Independent component accounting does not match the PyPSA objective")
    summary = {
        "framework": "PyPSA",
        "objective_kind": cfg["objective"],
        "objective_definition": "Net operating expenditure, including scenario electricity adders",
        "objective_dkk": float(n.objective),
        "hours": len(d),
        "variables": int(n.model.nvars),
        "constraints": int(n.model.ncons),
        "ptes_charge_mwh": float(d.ptes_charge_mw.sum()),
        "ptes_discharge_mwh": float(d.ptes_discharge_mw.sum()),
        "ptes_equivalent_cycles": float(d.ptes_discharge_mw.sum() / cfg["ptes"]["energy_mwh"]),
        "ptes_terminal_mwh": float(d.ptes_energy_mwh.iloc[-1]),
        "cost_contributions_dkk": contributions,
        "illustrative_settlement": settlement,
        "assumptions": deepcopy(cfg),
        "warnings": [
            "Representative scenario; demand boundary and 2019 HTF template require validation",
            "Planning capacities and scenario fuel, grid, availability and loss assumptions",
            "Pumping coefficient defaults to zero and settlement requires contractual verification",
            "Custom constraints must be rebuilt when re-solving an exported PyPSA network",
        ],
    }
    summary.update(_solver_info(n))
    if cfg["objective"] == "local" and cfg["settlement_boundary"] == "discharge_service":
        summary["charging_curtailed_mwh"] = float(
            (d.scheduled_ptes_charge_mw - d.ptes_charge_mw).sum()
        )
        summary["response_charging_policy"] = cfg.get("response", {}).get(
            "charging_policy", "curtailable"
        )
        if summary["response_charging_policy"] == "curtailable":
            summary["warnings"].append(
                "Curtailable charging is an analytical upstream-adaptation assumption"
            )
        else:
            summary["warnings"].append(
                "Fixed charging and final inventory approximately determine total discharge"
            )
    if not cfg["integer_operation"]:
        summary["warnings"].append(
            "LP relaxation; fractional operating modes are not an integer schedule"
        )
    if cfg["objective"] == "system":
        fuel = sum(
            float((d[p.name + "_fuel_mw"] * p.fuel_dkk_mwh).sum())
            for p in n._cph_plants.itertuples()
        )
        fuel += sum(
            float(d[f + "_boiler_heat_mw"].sum() / up[f + "_efficiency"] * up[f + "_dkk_mwh_fuel"])
            for f in ["gas", "oil", "bio"]
        )
        variable = sum(
            float(d[p.name + "_heat_mw"].sum() * p.vom_dkk_mwh_heat)
            for p in n._cph_plants.itertuples()
        )
        variable += sum(
            float(d[f + "_boiler_heat_mw"].sum() * up["boiler_vom_dkk_mwh"])
            for f in ["gas", "oil", "bio", "electric"]
        )
        variable += float(d.waste_heat_mw.sum() * up["waste_vom_dkk_mwh_heat"])
        upstream_el = (
            d.electric_boiler_heat_mw / up["electric_efficiency"]
            + d.regional_hp_heat_mw / up["heat_pump_cop"]
        )
        local_el = d.local_hp_electricity_mw + d.ptes_pump_electricity_mw
        power = (
            sum(d[p + "_power_mw"] for p in n._cph_plants.name)
            + d.waste_heat_mw * up["waste_power_heat_ratio"]
        )
        breakdown = {
            "fuel": fuel,
            "variable_om": variable,
            "hp_startups": starts,
            "electricity_spot_imports": float(
                ((upstream_el + local_el) * d.electricity_dkk_mwh).sum()
            ),
            "electricity_adders": float(
                (
                    upstream_el * up["electricity_adder_dkk_mwh"]
                    + local_el * hp["electricity_adder_dkk_mwh"]
                ).sum()
            ),
            "electricity_sales_credit": -float((power * d.electricity_dkk_mwh).sum()),
        }
        if not np.isclose(sum(breakdown.values()), n.objective, rtol=1e-8, atol=1e-4):
            raise RuntimeError("Independent economic accounting does not match the PyPSA objective")
        summary["operating_cost_breakdown_dkk"] = breakdown
        summary["waste_unused_availability_mwh"] = float(
            (np.minimum(d.waste_available_mw, up["waste_capacity_mw"]) - d.waste_heat_mw).sum()
        )
        summary["regional_accumulator_simultaneous_hours"] = {
            s: int(((d[s + "_charge_mw"] > 1e-6) & (d[s + "_discharge_mw"] > 1e-6)).sum())
            for s in up["accumulators"]
        }
        summary["warnings"].append(
            "Upstream CHP commitment and accumulator modes remain continuous"
        )
    return summary
