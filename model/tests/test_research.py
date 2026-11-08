from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from cph_dispatch.analysis import reconcile
from cph_dispatch.data import demo
from cph_dispatch.observations import compare_observations, load_observations
from cph_dispatch.optimisation import _optimise, build, solve
from cph_dispatch.study import evaluate_tariffs, study_cases
from cph_dispatch.tariffs import candidate_credit, candidate_prices, value_signals
from cph_dispatch.workflow import local_discharge_range


def test_proxy_data_cannot_be_called_metered(tmp_path):
    index = pd.date_range("2024-01-08", periods=4, freq="h", tz="UTC")
    path = tmp_path / "recorded.csv"
    pd.DataFrame(
        {
            "Q_storage_mwh": [10, 11, 9, 9],
            "E_charge_mwh": [0, 1, 0, 0],
            "E_discharge_mwh": [0, 0, 2, 0],
        },
        index=index,
    ).to_csv(path, index_label="time")
    with pytest.raises(ValueError, match="cannot label these as metered"):
        load_observations(path, kind="metered")
    obs, metadata = load_observations(path, kind="soc_proxy")
    d = pd.DataFrame(
        {"ptes_energy_mwh": 12, "ptes_charge_mw": 0, "ptes_discharge_mw": 0},
        index=pd.date_range(index[0] - pd.Timedelta(hours=1), periods=5, freq="h"),
    )
    joined, report = compare_observations(d, obs, metadata)
    assert len(joined) == 4
    assert report["model_hours_without_observations"] == 1
    assert metadata["flows_match_inventory_difference"]


def test_zero_cop_means_unavailable_and_asymmetric_power(config, plants):
    config["ptes"].update(charge_power_mw=12, discharge_power_mw=8)
    frame = demo(24)
    frame["city2_cop"] = 0.0
    result = solve(build(frame, config, plants))
    assert result.dispatch.city2_heat_mw.abs().max() < 1e-8
    assert result.dispatch.ptes_discharge_mw.max() <= 8 + 1e-6
    assert result.dispatch.ptes_charge_mw.max() <= 12 + 1e-6
    config["heat_pumps"]["policy"] = "must_run"
    with pytest.raises(ValueError, match="unavailable"):
        build(frame, config, plants)


def test_default_store_reaches_30mw_delivered_heat_in_both_directions(config, plants):
    config["objective"] = "local"
    config["settlement_boundary"] = "legacy_owned_store"
    config["ptes"]["loss_per_hour"] = 0.0
    frame = demo(48)
    frame["reference_tariff_dkk_mwh"] = np.tile(np.r_[np.full(12, 100), np.full(12, 600)], 2)
    actual = solve(build(frame, config, plants)).dispatch
    assert actual.ptes_discharge_mw.max() == pytest.approx(30.0, abs=1e-5)
    assert actual.ptes_charge_mw.max() == pytest.approx(30.0, abs=1e-5)


def test_value_spread_matches_paired_boundary_perturbation(config, plants):
    frame = demo(24)
    central = solve(build(frame, config, plants), prices=True)
    names = [
        "Link-status",
        "Link-start_up",
        "Link-shut_down",
        "ptes_charge_on",
        "ptes_discharge_on",
    ]
    modes = {name: central.network.model[name].solution.copy() for name in names}
    base = _optimise(build(frame, config, plants), relax=True, fixed_modes=modes)
    changed = build(frame, config, plants)
    time, epsilon = 8, 1e-4
    heat = pd.Series(0.0, index=changed.snapshots)
    heat.iloc[time] = -epsilon / (1 - config["network_loss_fraction"])
    inventory = pd.Series(0.0, index=changed.snapshots)
    inventory.iloc[time] = epsilon / config["ptes"]["discharge_efficiency"]
    changed.add("Load", "avoided_direct_heat", bus="heat_cph", p_set=heat)
    changed.add("Load", "extra_inventory_withdrawal", bus="ptes_inventory", p_set=inventory)
    _optimise(changed, relax=True, fixed_modes=modes)
    saving = (base.objective - changed.objective) / epsilon
    assert saving == pytest.approx(
        value_signals(central).discharge_value_spread_dkk_mwh.iloc[time], abs=0.03
    )
    spec = {"family": "monthly_mean_matched_value", "level": 5, "scale": 0.5}
    assert candidate_credit(central, spec).mean() == pytest.approx(5)


def test_absolute_heat_prices_and_monthly_controls_use_correct_boundaries():
    index = pd.date_range("2024-01-31T21:00Z", periods=5, freq="h")
    d = pd.DataFrame(
        {
            "reference_tariff_dkk_mwh": [300, 300, 350, 350, 350],
            "conditional_delivered_heat_value_dkk_mwh": [200, 400, 150, 250, 500],
            "conditional_inventory_value_dkk_mwh": [120, 128, 136, 144, 152],
            "discharge_pump_cost_dkk_mwh_heat": 5.0,
        },
        index=index,
    )
    central = SimpleNamespace(
        dispatch=d, summary={"assumptions": {"ptes": {"discharge_efficiency": 0.8}}}
    )
    spec = {"family": "inventory_value_price", "direct_basis": "delivered_marginal"}
    prices = candidate_prices(central, spec)
    np.testing.assert_allclose(prices.reference_tariff_dkk_mwh, [200, 400, 150, 250, 500])
    np.testing.assert_allclose(prices.discharge_service_price_dkk_mwh, [150, 160, 170, 180, 190])
    np.testing.assert_allclose(prices.discharge_discount_dkk_mwh, [50, 240, -20, 70, 310])
    spec["direct_basis"] = "monthly_mean_matched_marginal"
    matched = candidate_prices(central, spec)
    month = index.tz_convert("Europe/Copenhagen").strftime("%Y-%m")
    np.testing.assert_allclose(
        matched.reference_tariff_dkk_mwh.groupby(month).mean(),
        d.reference_tariff_dkk_mwh.groupby(month).mean(),
    )
    np.testing.assert_allclose(
        matched.discharge_service_price_dkk_mwh, prices.discharge_service_price_dkk_mwh
    )
    heat = candidate_prices(central, {"family": "heat_value_price"})
    np.testing.assert_allclose(
        heat.discharge_service_price_dkk_mwh, d.conditional_delivered_heat_value_dkk_mwh
    )

    bounded = candidate_prices(
        central,
        {"family": "bounded_mean_matched_value", "level": 5, "scale": 1, "lower": 0, "upper": 10},
    )
    credit = bounded.discharge_discount_dkk_mwh
    assert credit.min() >= 0
    assert credit.max() <= 10
    assert credit.max() - credit.min() > 1
    np.testing.assert_allclose(credit.groupby(month).mean(), [5, 5], atol=1e-10)
    np.testing.assert_allclose(bounded.reference_tariff_dkk_mwh, d.reference_tariff_dkk_mwh)
    assert (bounded.discharge_service_price_dkk_mwh <= d.reference_tariff_dkk_mwh).all()
    with pytest.raises(ValueError, match="within finite"):
        candidate_prices(central, {"family": "bounded_mean_matched_value", "level": 11})

    # Half of the positive value spread (50, 240, -20, 70, 310) goes to HTF; no premium.
    shared = candidate_prices(central, {"family": "shared_value", "scale": 0.5})
    np.testing.assert_allclose(shared.discharge_discount_dkk_mwh, [25, 120, 0, 35, 155])
    np.testing.assert_allclose(shared.reference_tariff_dkk_mwh, d.reference_tariff_dkk_mwh)


def test_study_reconciles_costs_and_preserves_matched_cases(config, plants):
    config["ptes"].update(
        energy_mwh=100, initial_mwh=50, terminal_mwh=50, pump_mwh_el_per_mwh_heat=0.005
    )
    config["heat_pumps"]["policy"] = "must_run"
    solutions, report, table = evaluate_tariffs(
        demo(48),
        config,
        plants,
        [
            {"name": "credit", "family": "constant", "level": 50},
            {
                "name": "absolute_price",
                "family": "inventory_value_price",
                "direct_basis": "delivered_marginal",
            },
        ],
    )
    assert report["best_tested_tariff"] in ("reference", "credit", "absolute_price")
    assert table.stakeholder_reconciliation_residual_dkk.abs().max() < 1e-5
    candidate = table.loc[table.tariff == "credit"].iloc[0]
    assert candidate.ptes_discharge_mwh > table.iloc[0].ptes_discharge_mwh
    ref, new = solutions["reference_corrective"], solutions["credit_corrective"]
    bounds = local_discharge_range(solutions["reference_local"])
    discharge = solutions["reference_local"].dispatch.ptes_discharge_mw.sum()
    assert bounds["minimum_mwh"] <= discharge + 1e-5
    assert bounds["maximum_mwh"] >= discharge - 1e-5
    mechanism = reconcile(ref.dispatch, new.dispatch, ref.summary, new.summary)
    assert abs(mechanism["production_reconciliation_residual_mwh"]) < 1e-5
    assert abs(mechanism["cost_reconciliation_residual_dkk"]) < 1e-4
    for label in ["reference", "credit", "absolute_price"]:
        local, actual = solutions[label + "_local"], solutions[label + "_corrective"]
        np.testing.assert_allclose(local.dispatch.hx_mw, actual.dispatch.hx_mw, atol=1e-6)
    dynamic = solutions["absolute_price_local"]
    np.testing.assert_allclose(
        dynamic.dispatch.reference_tariff_dkk_mwh,
        solutions["central"].dispatch.conditional_delivered_heat_value_dkk_mwh,
    )
    assert dynamic.raw.fun == pytest.approx(
        dynamic.summary["illustrative_settlement"]["local_expenditure_dkk"]
    )
    invalid = {"periods": [{"name": "outside", "start": "2025-01-01T00:00Z", "hours": 24}]}
    with pytest.raises(ValueError, match="outside"):
        list(study_cases(demo(48), config, invalid))
