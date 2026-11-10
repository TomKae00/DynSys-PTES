"""Daily rolling-horizon planning: plan the coming days, implement the first day, repeat.

Each case keeps its own physical state (PTES and accumulator content, PTES flows and
modes, heat-pump status). Every day the coordinated schedule is planned over the
look-ahead horizon from that state; for tariff cases the credit is derived from this
plan, HTF responds, and the upstream system is re-dispatched around HTF's decisions.
Only the first day is implemented. Planning and actual inputs are currently the same
(actual 2024 data); forecasts can replace the planning inputs later.
"""

from copy import deepcopy

import numpy as np
import pandas as pd

from .results import hourly_htf_bill, hourly_system_cost
from .tariffs import candidate_prices
from .workflow import coordinated, historical, response

REFERENCE, COORDINATED = "reference", "coordinated"


def initial_state(frame, config):
    """Measured PTES content at the start; accumulators half full; heat pumps off."""
    capacity = config["ptes"]["energy_mwh"]
    start = config["ptes"]["initial_mwh"]
    if "measured_inventory_mwh" in frame:
        before = frame.index[0] - pd.Timedelta(hours=1)
        inventory = frame.measured_inventory_mwh
        value = inventory.get(before, np.nan)
        start = value if np.isfinite(value) else inventory.iloc[0]
    hp = config["heat_pumps"]
    return {
        "ptes_mwh": float(np.clip(start, 0, capacity)),
        "charge_mw": 0.0,
        "discharge_mw": 0.0,
        "charge_on": [],
        "discharge_on": [],
        "accumulators": {
            name: spec["energy_mwh"] / 2 for name, spec in config["upstream"]["accumulators"].items()
        },
        "heat_pumps": {
            name: {"on": False, "hours": int(hp["minimum_down_hours"])}
            for name in ["city2", "groundwater"]
        },
    }


def with_state(config, state):
    """Configuration for one horizon that starts from the carried state."""
    cfg = deepcopy(config)
    ptes = cfg["ptes"]
    ptes["initial_mwh"] = float(np.clip(state["ptes_mwh"], 0, ptes["energy_mwh"]))
    ptes["initial_charge_mw"] = state["charge_mw"]
    ptes["initial_discharge_mw"] = state["discharge_mw"]
    ptes["previous_charge_on"] = list(state["charge_on"])
    ptes["previous_discharge_on"] = list(state["discharge_on"])
    for name, content in state["accumulators"].items():
        spec = cfg["upstream"]["accumulators"][name]
        spec["initial_mwh"] = float(np.clip(content, 0, spec["energy_mwh"]))
    for name, status in state["heat_pumps"].items():
        cfg["heat_pumps"][name]["initial_on"] = status["on"]
        cfg["heat_pumps"][name]["hours_in_state"] = max(int(status["hours"]), 1)
    return cfg


def advance(state, day, config):
    """State at the end of an implemented day."""
    reversal = config["ptes"]["reversal_hours"]
    last = day.iloc[-1]
    new = deepcopy(state)
    new["ptes_mwh"] = float(last.ptes_energy_mwh)
    new["charge_mw"] = float(last.ptes_charge_mw)
    new["discharge_mw"] = float(last.ptes_discharge_mw)
    for mode in ["charge", "discharge"]:
        history = list(state[mode + "_on"]) + [float(v) for v in day["ptes_" + mode + "_on"]]
        new[mode + "_on"] = history[-reversal:]
    for name in state["accumulators"]:
        new["accumulators"][name] = float(last[name + "_energy_mwh"])
    for name, status in state["heat_pumps"].items():
        column = name + "_on"
        if column not in day:
            continue
        values = (day[column].to_numpy() > 0.5).tolist()
        current = values[-1]
        run = 0
        for value in reversed(values):
            if value != current:
                break
            run += 1
        if run == len(values) and current == status["on"]:
            run += status["hours"]
        new["heat_pumps"][name] = {"on": bool(current), "hours": int(min(run, 10_000))}
    return new


def plan_config(config, state, window, rolling, terminal_value):
    """Coordinated planning: start from the state; value or fix the horizon-end content."""
    cfg = with_state(config, state)
    ptes = cfg["ptes"]
    rule = rolling.get("terminal", "mean_value")
    if rule == "measured":
        end = window.measured_inventory_mwh.iloc[-1]
        ptes["terminal_mwh"] = float(np.clip(end, 0, ptes["energy_mwh"]))
        ptes["terminal_value_dkk_mwh"] = None
    elif rule == "mean_value":
        if terminal_value is None:
            # First day: no earlier plan, so keep the content (cyclic window).
            ptes["terminal_mwh"] = ptes["initial_mwh"]
            ptes["terminal_value_dkk_mwh"] = None
        else:
            ptes["terminal_value_dkk_mwh"] = float(terminal_value)
    else:
        raise ValueError("Rolling terminal rule must be mean_value or measured")
    return cfg


def run_case(frame, config, plants, case, *, rolling, spec=None, progress=None):
    """Implement one case day by day; return the implemented hours and plan diagnostics."""
    horizon = int(rolling.get("horizon_hours", 168))
    step = int(rolling.get("step_hours", 24))
    if not 2 <= step <= horizon:
        raise ValueError("Rolling step must be at least two hours and within the horizon")
    state = initial_state(frame, config)
    terminal_value = None
    days, plans = [], []
    for start in range(0, len(frame), step):
        window = frame.iloc[start : start + horizon]
        if len(window) < 2:
            break
        if case == REFERENCE:
            replay = with_state(config, state)
            _, realized = historical(window, replay, plants)
            implemented = realized.dispatch
        else:
            planning = plan_config(config, state, window, rolling, terminal_value)
            central = coordinated(window, planning, plants, prices=True)
            terminal_value = float(central.dispatch.conditional_delivered_heat_value_dkk_mwh.mean())
            plans.append(
                {
                    "start": window.index[0],
                    "terminal_value_dkk_mwh": planning["ptes"].get("terminal_value_dkk_mwh"),
                    "planned_end_mwh": float(central.dispatch.ptes_energy_mwh.iloc[-1]),
                    "mean_delivered_value_dkk_mwh": terminal_value,
                }
            )
            if case == COORDINATED:
                implemented = central.dispatch
            else:
                pricing = candidate_prices(central, spec)
                local_cfg = with_state(config, state)
                local_cfg["ptes"]["terminal_mwh"] = float(
                    np.clip(central.dispatch.ptes_energy_mwh.iloc[-1], 0, config["ptes"]["energy_mwh"])
                )
                local_cfg["ptes"]["terminal_value_dkk_mwh"] = None
                _, realized = response(
                    window,
                    local_cfg,
                    plants,
                    central,
                    pricing.discharge_discount_dkk_mwh,
                    direct_tariff=pricing.reference_tariff_dkk_mwh,
                    follow_schedule=bool(spec.get("follow_schedule", False)),
                )
                implemented = realized.dispatch
        day = implemented.iloc[: min(step, len(window))].copy()
        state = advance(state, day, config)
        days.append(day)
        if progress is not None:
            progress(case, window.index[0])
    realized = pd.concat(days)
    costs = hourly_htf_bill(realized, config)
    realized["system_cost_dkk"] = hourly_system_cost(realized, config, plants)
    realized["htf_bill_dkk"] = costs.htf_bill_dkk
    realized["supplier_heat_revenue_dkk"] = costs.supplier_heat_revenue_dkk
    return realized, pd.DataFrame(plans)


def summarise(results, config):
    """Annual totals and stakeholder effects relative to the reference."""
    if REFERENCE not in results or COORDINATED not in results:
        raise ValueError("Rolling summary needs the reference and coordinated cases")
    coordinated_hours = results[COORDINATED]
    # Different final contents are valued at the coordinated schedule's mean delivered
    # heat value over the last week.
    value = float(coordinated_hours.conditional_delivered_heat_value_dkk_mwh.iloc[-168:].mean())
    end_ref = float(results[REFERENCE].ptes_energy_mwh.iloc[-1])

    def adjusted(d):
        return float(d.system_cost_dkk.sum()) - (float(d.ptes_energy_mwh.iloc[-1]) - end_ref) * value

    reference, coordinated_cost = adjusted(results[REFERENCE]), adjusted(coordinated_hours)
    gap = reference - coordinated_cost
    weeks = results[REFERENCE].index.tz_convert("Europe/Copenhagen").strftime("%G-%V")
    rows = []
    for case, d in results.items():
        saving = reference - adjusted(d)
        bill = float(results[REFERENCE].htf_bill_dkk.sum() - d.htf_bill_dkk.sum())
        weekly_system = (results[REFERENCE].system_cost_dkk - d.system_cost_dkk).groupby(weeks).sum()
        weekly_bill = (results[REFERENCE].htf_bill_dkk - d.htf_bill_dkk).groupby(weeks).sum()
        both = int(((weekly_bill >= -1) & (weekly_system - weekly_bill >= -1)).sum())
        rows.append(
            {
                "case": case,
                "system_cost_dkk": float(d.system_cost_dkk.sum()),
                "terminal_adjustment_dkk": (float(d.ptes_energy_mwh.iloc[-1]) - end_ref) * value,
                "system_saving_dkk": saving,
                "htf_bill_saving_dkk": bill,
                "upstream_gain_dkk": saving - bill,
                "heat_revenue_change_dkk": float(
                    d.supplier_heat_revenue_dkk.sum()
                    - results[REFERENCE].supplier_heat_revenue_dkk.sum()
                ),
                "recovered_share": saving / gap if gap else np.nan,
                "ptes_charge_mwh": float(d.ptes_charge_mw.sum()),
                "ptes_discharge_mwh": float(d.ptes_discharge_mw.sum()),
                "equivalent_cycles": float(d.ptes_discharge_mw.sum() / config["ptes"]["energy_mwh"]),
                "ptes_end_mwh": float(d.ptes_energy_mwh.iloc[-1]),
                "local_hp_heat_mwh": float((d.city2_heat_mw + d.groundwater_heat_mw).sum()),
                "weeks": int(weekly_bill.size),
                "weeks_both_gain": both,
            }
        )
    table = pd.DataFrame(rows)
    table.attrs["coordination_value_dkk"] = gap
    table.attrs["terminal_value_dkk_mwh"] = value
    return table
