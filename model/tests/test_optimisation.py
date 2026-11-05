import json
from pathlib import Path

import numpy as np
import pypsa
import pytest

from cph_dispatch.cli import main
from cph_dispatch.data import demo
from cph_dispatch.optimisation import _optimise, build, conditional_prices, solve
from cph_dispatch.workflow import compare


def test_dispatch_physics_and_accounting(config, plants, tmp_path):
    frame = demo(72)
    config["solver"]["mip_rel_gap"] = 0.0001
    result = solve(build(frame, config, plants), prices=True)
    assert isinstance(result.network, pypsa.Network)
    result.network.export_to_netcdf(tmp_path / "network.nc")
    reloaded = pypsa.Network(tmp_path / "network.nc")
    assert reloaded.meta["snapshot_timezone"] == "UTC"
    np.testing.assert_allclose(reloaded.stores_t.e.ptes, result.network.stores_t.e.ptes)
    assert np.isfinite(reloaded.buses_t.marginal_price.heat_cph).all()
    np.testing.assert_allclose(reloaded.links_t.status.ptes_charge, result.dispatch.ptes_charge_on)
    d = result.dispatch
    np.testing.assert_allclose(
        d.hx_mw + d.ptes_discharge_mw + d.city2_heat_mw + d.groundwater_heat_mw,
        d.htf_demand_mw,
        atol=1e-6,
    )
    previous = np.r_[config["ptes"]["initial_mwh"], d.ptes_energy_mwh.iloc[:-1]]
    np.testing.assert_allclose(
        d.ptes_energy_mwh,
        previous * (1 - config["ptes"]["loss_per_hour"]) + d.ptes_charge_mw - d.ptes_discharge_mw,
        atol=1e-6,
    )
    assert d.ptes_energy_mwh.iloc[-1] == pytest.approx(config["ptes"]["terminal_mwh"])
    assert (d.ptes_charge_mw * d.ptes_discharge_mw).abs().max() < 1e-6
    for name in ["AMV", "AVV"]:
        spec = config["upstream"]["accumulators"][name]
        assert d[name + "_energy_mwh"].iloc[-1] == pytest.approx(spec["energy_mwh"] / 2)
        assert (d[name + "_charge_mw"] + d[name + "_discharge_mw"]).max() <= spec["power_mw"] + 1e-6
    for name in ["city2", "groundwater"]:
        on = d[name + "_on"].round().astype(int).to_numpy()
        starts = d[name + "_start"].round().astype(int).to_numpy()
        stops = d[name + "_stop"].round().astype(int).to_numpy()
        np.testing.assert_array_equal(on - np.r_[0, on[:-1]], starts - stops)
        for t in np.flatnonzero(starts):
            assert np.all(on[t : t + 2] == 1)
        for t in np.flatnonzero(stops):
            assert np.all(on[t : t + 2] == 0)
    for column, minimum in [("ptes_charge_mw", 10), ("ptes_discharge_mw", 5)]:
        flow = d[column].to_numpy()
        assert np.all((flow < 1e-6) | (flow >= minimum - 1e-6))
        assert np.abs(np.diff(np.r_[0, flow])).max() <= 12 + 1e-6
        assert flow.max() <= 23 + 1e-6
    for lag in [1, 2]:
        assert np.all(
            d.ptes_charge_on.to_numpy()[:-lag] + d.ptes_discharge_on.to_numpy()[lag:] < 1.00001
        )
        assert np.all(
            d.ptes_discharge_on.to_numpy()[:-lag] + d.ptes_charge_on.to_numpy()[lag:] < 1.00001
        )
    for plant in plants.itertuples():
        q, p, f = [d[plant.name + s] for s in ["_heat_mw", "_power_mw", "_fuel_mw"]]
        assert f.max() <= plant.fuel_mw * plant.availability + 1e-6
        if plant.kind == "backpressure":
            b = d[plant.name + "_bypass_mw"]
            np.testing.assert_allclose(q, p / plant.cm + b, atol=1e-6)
            np.testing.assert_allclose(f, p / plant.eta_el + b / plant.eta_bypass, atol=1e-6)
        else:
            assert (p + plant.cv * q - plant.eta_el * f).max() <= 1e-6
            assert (plant.cm * q - p).max() <= 1e-6
    q_chp = sum(d[p + "_heat_mw"] for p in plants.name)
    q_peak = sum(d[f + "_boiler_heat_mw"] for f in ["gas", "oil", "bio", "electric"])
    q_store = sum(d[s + "_discharge_mw"] - d[s + "_charge_mw"] for s in ["AMV", "AVV"])
    np.testing.assert_allclose(
        q_chp + q_peak + q_store + d.waste_heat_mw + d.regional_hp_heat_mw,
        (d.regional_demand_mw - d.htf_demand_mw + d.hx_mw + d.ptes_charge_mw)
        / (1 - config["network_loss_fraction"]),
        atol=1e-6,
    )
    assert sum(result.summary["cost_contributions_dkk"].values()) == pytest.approx(result.raw.fun)
    assert sum(result.summary["operating_cost_breakdown_dkk"].values()) == pytest.approx(
        result.raw.fun
    )
    settlement = result.summary["illustrative_settlement"]
    assert settlement["heat_purchase_dkk"] - settlement["discharge_credit_dkk"] == pytest.approx(
        settlement["supplier_local_heat_revenue_dkk"]
    )


def test_thermal_capacity_with_changing_cop(config, plants):
    frame = demo(24)
    frame["electricity_dkk_mwh"] = -1000
    frame["city2_cop"] = np.linspace(2, 6, len(frame))
    config["objective"] = "local"
    config["settlement_boundary"] = "legacy_owned_store"
    d = solve(build(frame, config, plants)).dispatch
    assert d.city2_heat_mw.max() <= 1.34 + 1e-7
    np.testing.assert_allclose(
        d.local_hp_electricity_mw,
        d.city2_heat_mw / d.city2_cop + d.groundwater_heat_mw / d.groundwater_cop,
    )


def test_prices_match_fixed_commitment_demand_perturbation(config, plants):
    frame = demo(24)
    model = build(frame, config, plants)
    result = solve(model)
    dual = conditional_prices(model, result.raw)
    names = [
        "Link-status",
        "Link-start_up",
        "Link-shut_down",
        "ptes_charge_on",
        "ptes_discharge_on",
    ]
    modes = {k: model.model[k].solution.copy() for k in names}
    fixed = _optimise(build(frame, config, plants), relax=True, fixed_modes=modes)
    perturbed = frame.copy()
    perturbed.iloc[8, perturbed.columns.get_loc("regional_demand_mw")] += 0.001
    second = _optimise(build(perturbed, config, plants), relax=True, fixed_modes=modes)
    # Demand is delivered heat; the balance dual is per unit of upstream heat.
    assert (second.objective - fixed.objective) / 0.001 == pytest.approx(
        dual[8] / (1 - config["network_loss_fraction"]), rel=1e-4
    )


def test_endogenous_price_response(config, plants):
    config["objective"] = "local"
    config["settlement_boundary"] = "legacy_owned_store"
    frame = demo(72)
    frame["reference_tariff_dkk_mwh"] = np.tile(np.r_[np.full(12, 100), np.full(12, 600)], 3)
    baseline = solve(build(frame, config, plants))
    config["ptes"]["power_mw"] = 0.001
    config["ptes"]["min_charge_mw"] = 0
    config["ptes"]["min_discharge_mw"] = 0
    config["ptes"]["loss_per_hour"] = 0
    without = solve(build(frame, config, plants))
    assert baseline.dispatch.ptes_discharge_mw.sum() > 100
    assert baseline.raw.fun < without.raw.fun


def test_failure_is_explicit(config, plants, tmp_path):
    frame = demo(24)
    frame["htf_demand_mw"] = 500
    inputs, output = tmp_path / "infeasible.csv", tmp_path / "result"
    frame.to_csv(inputs)
    assert main(["solve", "--inputs", str(inputs), "--output", str(output)]) == 1
    assert not output.exists()
    frame["regional_demand_mw"] = 1
    with pytest.raises(ValueError, match="Regional demand smaller"):
        build(frame, config, plants)


def test_discharge_credit_is_transfer_not_resource_cost(config, plants):
    frame = demo(24)
    base = solve(build(frame, config, plants))
    config["discharge_discount_dkk_mwh"] = 100
    second = solve(build(frame, config, plants))
    assert base.raw.fun == pytest.approx(second.raw.fun)
    assert second.summary["illustrative_settlement"]["discharge_credit_dkk"] == pytest.approx(
        second.dispatch.ptes_discharge_mw.sum() * 100
    )


def test_discharge_boundary_charging_schedule_and_bill(config, plants):
    frame = demo(48)
    central = solve(build(frame, config, plants))
    config["objective"] = "local"
    config["response"]["charging_policy"] = "fixed"
    with pytest.raises(ValueError, match="charging schedule"):
        build(frame, config, plants)
    frame["scheduled_ptes_charge_mw"] = central.dispatch.ptes_charge_mw
    config["discharge_discount_dkk_mwh"] = 50
    local = solve(build(frame, config, plants))
    d = local.dispatch
    np.testing.assert_allclose(d.ptes_charge_mw, frame.scheduled_ptes_charge_mw, atol=1e-6)
    bill = (
        (d.hx_mw + d.ptes_discharge_mw) * d.reference_tariff_dkk_mwh - 50 * d.ptes_discharge_mw
    ).sum()
    s = local.summary["illustrative_settlement"]
    assert s["supplier_local_heat_revenue_dkk"] == pytest.approx(bill)
    assert local.raw.fun == pytest.approx(s["local_expenditure_dkk"])


def test_optional_gurobi_matches_highs(config, plants):
    pytest.importorskip("gurobipy")
    frame = demo(8)
    config["solver"]["mip_rel_gap"] = 1e-8
    highs = solve(build(frame, config, plants), prices=True)
    config["solver"]["backend"] = "gurobi"
    gurobi = solve(build(frame, config, plants), prices=True)
    assert gurobi.raw.fun == pytest.approx(highs.raw.fun, rel=1e-7)
    assert np.isfinite(gurobi.dispatch.conditional_upstream_value_dkk_mwh).all()


def test_efficiency_loss_and_pumping_units_match_native_energy_balances(config, plants):
    config["network_loss_fraction"] = 0.07
    config["ptes"].update(
        charge_efficiency=0.97, discharge_efficiency=0.95, pump_mwh_el_per_mwh_heat=0.003
    )
    result = solve(build(demo(24), config, plants))
    d, ptes = result.dispatch, config["ptes"]
    previous = np.r_[ptes["initial_mwh"], d.ptes_energy_mwh.iloc[:-1]]
    np.testing.assert_allclose(
        d.ptes_energy_mwh,
        previous * (1 - ptes["loss_per_hour"])
        + 0.97 * d.ptes_charge_mw
        - d.ptes_discharge_mw / 0.95,
        atol=1e-6,
    )
    exported = sum(d[p + "_power_mw"] for p in plants.name)
    exported += d.waste_heat_mw * config["upstream"]["waste_power_heat_ratio"]
    consumed = (
        d.local_hp_electricity_mw
        + d.ptes_pump_electricity_mw
        + d.regional_hp_heat_mw / config["upstream"]["heat_pump_cop"]
        + d.electric_boiler_heat_mw / config["upstream"]["electric_efficiency"]
    )
    np.testing.assert_allclose(d.electricity_market_net_mw, consumed - exported, atol=1e-6)
    np.testing.assert_allclose(
        d.ptes_pump_electricity_mw, 0.003 * (d.ptes_charge_mw + d.ptes_discharge_mw), atol=1e-8
    )


def test_direct_formulation_reference_objectives(config, plants):
    reference = json.loads((Path(__file__).parent / "fixtures/direct_reference.json").read_text())
    plants = plants.copy()
    plants.bypass_mw = 0
    config["solver"]["mip_rel_gap"] = 1e-8
    frame = demo(24)
    system = solve(build(frame, config, plants))
    assert system.raw.fun == pytest.approx(reference["system_objective_dkk"], rel=0, abs=0.1)
    config["objective"] = "local"
    config["settlement_boundary"] = "legacy_owned_store"
    owned = solve(build(frame, config, plants))
    assert owned.raw.fun == pytest.approx(reference["legacy_owned_objective_dkk"], rel=0, abs=0.1)
    config["settlement_boundary"] = "discharge_service"
    config["response"]["charging_policy"] = "fixed"
    frame["scheduled_ptes_charge_mw"] = np.maximum(reference["scheduled_charge_mw"], 0)
    fixed = solve(build(frame, config, plants))
    assert fixed.raw.fun == pytest.approx(reference["fixed_response_objective_dkk"], rel=0, abs=0.1)


def test_full_bypass_mode_reaches_documented_heat_capacity(config, plants):
    plants = plants.loc[plants.name == "AMV4"].copy()
    plants.availability = 1.0
    config["heat_pumps"]["policy"] = "must_run"
    config["network_loss_fraction"] = 0.0
    config["ptes"]["loss_per_hour"] = 0.0
    for spec in config["upstream"]["accumulators"].values():
        spec["loss_per_hour"] = 0.0
    for key in ["gas_mw", "oil_mw", "bio_mw", "electric_mw", "heat_pump_mw"]:
        config["upstream"][key] = 0.0
    frame = demo(8)
    frame["waste_available_mw"] = 0.0
    frame["regional_demand_mw"] = 550 + 2.84
    frame["htf_demand_mw"] = 0.5 + 2.84
    result = solve(build(frame, config, plants))
    np.testing.assert_allclose(result.dispatch.AMV4_heat_mw, 550, atol=1e-6)
    np.testing.assert_allclose(result.dispatch.AMV4_power_mw, 0, atol=1e-6)
    np.testing.assert_allclose(result.dispatch.AMV4_fuel_mw, 487, atol=1e-6)


def test_curtailable_response_allows_lower_utilisation_and_accounts_upstream_cost(config, plants):
    config["heat_pumps"]["policy"] = "must_run"
    config["ptes"].update(
        energy_mwh=100,
        initial_mwh=50,
        terminal_mwh=50,
        loss_per_hour=0.0,
        pump_mwh_el_per_mwh_heat=0.005,
    )
    for spec in config["upstream"]["accumulators"].values():
        spec.update(energy_mwh=0.01, power_mw=0.001, loss_per_hour=0.0)
    solutions, report = compare(demo(72), config, plants, discount=50)
    ref, candidate = report["cases"]["reference"], report["cases"]["candidate"]
    assert ref["ptes_discharge_mwh"] < 1e-5
    assert candidate["ptes_discharge_mwh"] > 20
    assert ref["charging_curtailed_mwh"] > 20
    assert candidate["ptes_terminal_mwh"] == pytest.approx(50)
    for label in ["reference", "candidate"]:
        local = solutions[label + "_local"].dispatch
        adjusted = solutions[label + "_corrective"].dispatch
        np.testing.assert_allclose(local.hx_mw, adjusted.hx_mw, atol=1e-6)
        np.testing.assert_allclose(local.ptes_discharge_mw, adjusted.ptes_discharge_mw, atol=1e-6)
        assert np.all(adjusted.ptes_charge_mw <= local.scheduled_ptes_charge_mw + 1e-6)
        assert adjusted.ptes_energy_mwh.iloc[-1] == pytest.approx(50)
    expected = solutions["reference_corrective"].raw.fun - solutions["candidate_corrective"].raw.fun
    assert report["candidate_vs_reference"]["system_operating_cost_saving_dkk"] == pytest.approx(
        expected
    )
