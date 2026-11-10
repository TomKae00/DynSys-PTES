import numpy as np
import pandas as pd

from cph_dispatch.data import demo
from cph_dispatch.optimisation import build, solve
from cph_dispatch.results import hourly_htf_bill, hourly_system_cost
from cph_dispatch.rolling import COORDINATED, REFERENCE, advance, initial_state, run_case, summarise


def test_carried_state_constrains_the_first_hours(config, plants):
    frame = demo(24)
    config["ptes"].update(
        initial_mwh=1500,
        terminal_mwh=1500,
        initial_discharge_mw=29.0,
        previous_discharge_on=[1.0, 1.0],
    )
    d = solve(build(frame, config, plants)).dispatch
    ramp = config["ptes"]["ramp_mw_h"]
    # Ramp-up relative to the flow before the horizon, no charging during the lock-out.
    assert d.ptes_discharge_mw.iloc[0] <= 29.0 + ramp + 1e-6
    assert (d.ptes_charge_mw.iloc[: config["ptes"]["reversal_hours"]] <= 1e-6).all()
    assert (d.ptes_discharge_mw.diff().abs().iloc[1:] <= ramp + 1e-6).all()


def test_terminal_value_replaces_fixed_end_and_keeps_accounting(config, plants):
    frame = demo(24)
    config["ptes"].update(initial_mwh=1500, terminal_value_dkk_mwh=1e4)
    result = solve(build(frame, config, plants))
    # A high value of stored heat fills the store instead of returning to 1500 MWh.
    assert result.dispatch.ptes_energy_mwh.iloc[-1] > 1500 + 1
    breakdown = sum(result.summary["operating_cost_breakdown_dkk"].values())
    np.testing.assert_allclose(breakdown, result.summary["objective_dkk"], rtol=1e-8, atol=1e-3)
    hourly = hourly_system_cost(result.dispatch, config, plants).sum()
    np.testing.assert_allclose(hourly, result.summary["objective_dkk"], rtol=1e-8, atol=1e-3)


def test_advance_tracks_heat_pump_runs_and_mode_history(config):
    frame = demo(6)
    state = initial_state(frame, config)
    day = pd.DataFrame(
        {
            "ptes_energy_mwh": [1000.0] * 6,
            "ptes_charge_mw": [0, 0, 0, 0, 10, 12.0],
            "ptes_discharge_mw": [0.0] * 6,
            "ptes_charge_on": [0, 0, 0, 0, 1, 1.0],
            "ptes_discharge_on": [0.0] * 6,
            "AMV_energy_mwh": [400.0] * 6,
            "AVV_energy_mwh": [900.0] * 6,
            "city2_on": [0, 0, 1, 1, 1, 1.0],
            "groundwater_on": [0.0] * 6,
        }
    )
    new = advance(state, day, config)
    assert new["charge_mw"] == 12.0 and new["charge_on"] == [1.0, 1.0]
    assert new["heat_pumps"]["city2"] == {"on": True, "hours": 4}
    # Off all day after starting off: the off period continues.
    assert new["heat_pumps"]["groundwater"]["hours"] == 6 + state["heat_pumps"]["groundwater"]["hours"]


def test_rolling_cases_are_consistent(config, plants):
    frame = demo(72)
    frame["metered_charge_mw"] = 0.0
    frame["metered_discharge_mw"] = 0.0
    frame.iloc[30:40, frame.columns.get_loc("metered_discharge_mw")] = 10.0
    frame["measured_inventory_mwh"] = 1500.0
    rolling = {"horizon_hours": 48, "step_hours": 24}
    results = {
        case: run_case(frame, config, plants, case, rolling=rolling)[0]
        for case in [REFERENCE, COORDINATED]
    }
    spec = {"name": "hourly", "family": "constant", "level": 5}
    results["hourly"] = run_case(frame, config, plants, "hourly", rolling=rolling, spec=spec)[0]
    for d in results.values():
        assert len(d) == 72
        assert d.index.is_monotonic_increasing and not d.index.has_duplicates
        # Content carried across days: hourly balance holds at day boundaries too.
        loss = config["ptes"]["loss_per_hour"]
        previous = d.ptes_energy_mwh.shift(1).iloc[1:]
        balance = (
            d.ptes_energy_mwh.iloc[1:]
            - previous * (1 - loss)
            - d.ptes_charge_mw.iloc[1:]
            + d.ptes_discharge_mw.iloc[1:]
        )
        assert balance.abs().max() < 1e-4
    np.testing.assert_allclose(results[REFERENCE].ptes_discharge_mw, frame.metered_discharge_mw, atol=1e-6)
    table = summarise(results, config).set_index("case")
    assert table.loc[REFERENCE, "system_saving_dkk"] == 0
    np.testing.assert_allclose(table.loc[COORDINATED, "recovered_share"], 1.0)
    # Transfers cancel: system saving = HTF bill saving + upstream gain.
    np.testing.assert_allclose(
        table.system_saving_dkk, table.htf_bill_saving_dkk + table.upstream_gain_dkk
    )
    bill = hourly_htf_bill(results["hourly"], config)
    np.testing.assert_allclose(bill.htf_bill_dkk, results["hourly"].htf_bill_dkk)


def test_full_store_still_charging_can_stop(config, plants):
    frame = demo(24)
    config["ptes"].update(
        initial_mwh=config["ptes"]["energy_mwh"],
        terminal_value_dkk_mwh=0.0,
        initial_charge_mw=30.0,
        previous_charge_on=[1.0, 1.0],
    )
    d = solve(build(frame, config, plants)).dispatch
    assert d.ptes_charge_mw.iloc[0] <= 1e-6
