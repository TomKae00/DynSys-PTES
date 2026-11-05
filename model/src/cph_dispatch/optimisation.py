"""PyPSA networks for coordinated Copenhagen dispatch and local HTF response."""

from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pypsa
import xarray as xr

from .results import collect, summarise


def validate_inputs(frame, config, plants):
    required = [
        "regional_demand_mw",
        "htf_demand_mw",
        "waste_available_mw",
        "electricity_dkk_mwh",
        "city2_cop",
        "groundwater_cop",
        "reference_tariff_dkk_mwh",
    ]
    if len(frame) < 2 or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("At least two timezone-aware hourly snapshots required")
    if frame.index.has_duplicates or not np.all(np.diff(frame.index.asi8) == 3600 * 10**9):
        raise ValueError("Snapshots must be unique and consecutive UTC hours")
    if not np.isfinite(frame[required].to_numpy(dtype=float)).all():
        raise ValueError("Inputs contain non-finite values")
    if (frame[["regional_demand_mw", "htf_demand_mw", "waste_available_mw"]] < 0).any().any():
        raise ValueError("Negative heat demand or waste availability")
    if (frame[["city2_cop", "groundwater_cop"]] <= 1).any().any():
        raise ValueError("Heat-pump COP must exceed one")
    if config["demand_boundary"] not in ("assumed_gross_including_htf", "residual_excluding_htf"):
        raise ValueError("Unresolved demand boundary; net withdrawals need historical HTF metering")
    if config["objective"] not in ("system", "local"):
        raise ValueError("Objective must be system or local")
    if config["settlement_boundary"] not in ("discharge_service", "legacy_owned_store"):
        raise ValueError("Unknown settlement boundary")
    if config.get("response", {}).get("charging_policy", "curtailable") not in (
        "fixed",
        "curtailable",
    ):
        raise ValueError("Charging policy must be fixed or curtailable")
    if config["objective"] == "local" and config["settlement_boundary"] == "discharge_service":
        if (
            "scheduled_ptes_charge_mw" not in frame
            or not np.isfinite(frame.scheduled_ptes_charge_mw).all()
            or (frame.scheduled_ptes_charge_mw < -1e-7).any()
        ):
            raise ValueError(
                "Discharge-service response needs a complete nonnegative charging schedule"
            )
    if not 0 <= config["network_loss_fraction"] < 1:
        raise ValueError("Network loss fraction must be in [0,1)")
    for spec in [config["ptes"], *config["upstream"]["accumulators"].values()]:
        if spec["energy_mwh"] <= 0 or spec["power_mw"] <= 0:
            raise ValueError("Storage capacities must be positive")
        if not 0 <= spec["loss_per_hour"] < 1:
            raise ValueError("Storage hourly loss must be in [0,1)")
    ptes = config["ptes"]
    if not all(0 <= ptes[k] <= ptes["energy_mwh"] for k in ["initial_mwh", "terminal_mwh"]):
        raise ValueError("PTES boundary inventories exceed capacity")
    if not all(0 < ptes[k] <= 1 for k in ["charge_efficiency", "discharge_efficiency"]):
        raise ValueError("PTES efficiencies must be in (0,1]")
    if not 0 <= config["hx"]["minimum_mw"] <= config["hx"]["capacity_mw"]:
        raise ValueError("Invalid HX bounds")
    if plants.name.duplicated().any() or not plants.kind.isin(["backpressure", "extraction"]).all():
        raise ValueError("Plant names must be unique and kinds explicitly supported")
    if ((plants.availability < 0) | (plants.availability > 1)).any():
        raise ValueError("Availability factors must be in [0,1]")
    if (plants.fuel_dkk_mwh < 0).any():
        raise ValueError("Negative CHP fuel prices need an explicit fuel-disposal formulation")
    if (plants.loc[plants.kind == "extraction", "cv"] <= 0).any():
        raise ValueError("Extraction CHP requires a positive Cv")


def _initial_loss(n, name, bus, initial, loss):
    # PyPSA 1.0.4's Store balance inserts e_initial without first-hour decay.
    # This explicit inventory-bus load gives E_0 the same start-of-hour meaning
    # as every later E_(t-1), while preserving the native e_initial value.
    if initial * loss:
        values = pd.Series(0.0, index=n.snapshots)
        values.iloc[0] = initial * loss
        n.add("Load", name + "_initial_loss", bus=bus, p_set=values)


def _storage(n, name, spec, heat_bus, *, initial):
    store_bus = name + "_inventory"
    n.add("Bus", store_bus, carrier="heat")
    n.add(
        "Store",
        name,
        bus=store_bus,
        e_nom=spec["energy_mwh"],
        e_initial=initial,
        standing_loss=spec["loss_per_hour"],
        carrier="heat",
    )
    _initial_loss(n, name, store_bus, initial, spec["loss_per_hour"])
    n.add(
        "Link",
        name + "_charge",
        bus0=heat_bus,
        bus1=store_bus,
        p_nom=spec["power_mw"],
        efficiency=1.0,
        carrier="heat",
    )
    n.add(
        "Link",
        name + "_discharge",
        bus0=store_bus,
        bus1=heat_bus,
        p_nom=spec["power_mw"],
        efficiency=1.0,
        carrier="heat",
    )


def build(frame, config, plants, *, fixed_local=None):
    """Return a real PyPSA Network; its timezone-naive snapshots explicitly denote UTC."""
    config = deepcopy(config)
    validate_inputs(frame, config, plants)
    n = pypsa.Network()
    n.set_snapshots(frame.index.tz_convert("UTC").tz_localize(None).rename("snapshot"))
    n._cph_inputs, n._cph_config, n._cph_plants = frame.copy(), config, plants.copy()
    n._cph_fixed_local = fixed_local
    if fixed_local is not None:
        cols = ["hx_mw", "ptes_discharge_mw", "city2_heat_mw", "groundwater_heat_mw"]
        if (
            not fixed_local.index.equals(frame.index)
            or not np.isfinite(fixed_local[cols]).all().all()
        ):
            raise ValueError("Corrective dispatch needs an exactly aligned complete local result")
        if "scheduled_ptes_charge_mw" not in frame:
            raise ValueError("Corrective dispatch needs the announced charging schedule")
    n.meta = {
        "workflow": "cph_dispatch_pypsa",
        "snapshot_timezone": "UTC",
        "config": config,
        "custom_constraints_require_rebuild": True,
        "storage_initial_loss": "Explicit first-hour inventory-bus load; initial inventory is before losses",
    }
    d = frame.copy()
    d.index = n.snapshots
    system = config["objective"] == "system"
    owned = config["settlement_boundary"] == "legacy_owned_store"
    delivery = 1 - config["network_loss_fraction"] if system else 1.0
    n._cph_delivery = delivery
    for carrier in ["heat", "electricity", "fuel", "waste"]:
        n.add("Carrier", carrier)
    for name, carrier in [
        ("heat_cph", "heat"),
        ("heat_htf", "heat"),
        ("electricity", "electricity"),
        ("ptes_inventory", "heat"),
    ]:
        n.add("Bus", name, carrier=carrier)
    # One signed market exchange avoids independent import/export arbitrage variables.
    exchange_capacity = (
        float(plants.power_mw.sum())
        + config["upstream"]["waste_capacity_mw"]
        + config["upstream"]["electric_mw"]
        + 1000
    )
    n.add(
        "Generator",
        "electricity_market",
        bus="electricity",
        p_nom=exchange_capacity,
        p_min_pu=-1.0,
        marginal_cost=d.electricity_dkk_mwh,
        carrier="electricity",
    )
    tariff = d.reference_tariff_dkk_mwh
    discount = d.get("discharge_discount_dkk_mwh", config["discharge_discount_dkk_mwh"])
    hx = config["hx"]
    n.add(
        "Link",
        "hx",
        bus0="heat_cph",
        bus1="heat_htf",
        efficiency=delivery,
        p_nom=hx["capacity_mw"] / delivery,
        p_min_pu=hx["minimum_mw"] / hx["capacity_mw"],
        marginal_cost=0 if system else tariff,
        carrier="heat",
    )
    ptes = config["ptes"]
    n.add(
        "Store",
        "ptes",
        bus="ptes_inventory",
        e_nom=ptes["energy_mwh"],
        e_initial=ptes["initial_mwh"],
        standing_loss=ptes["loss_per_hour"],
        carrier="heat",
    )
    _initial_loss(n, "ptes", "ptes_inventory", ptes["initial_mwh"], ptes["loss_per_hour"])
    adder = config["heat_pumps"]["electricity_adder_dkk_mwh"]
    pump = ptes["pump_mwh_el_per_mwh_heat"]
    charge_pumping = system or owned
    charge_extra = (
        {"bus2": "electricity", "efficiency2": -pump * delivery} if charge_pumping and pump else {}
    )
    discharge_extra = (
        {"bus2": "electricity", "efficiency2": -pump * ptes["discharge_efficiency"]} if pump else {}
    )
    n.add(
        "Link",
        "ptes_charge",
        bus0="heat_cph",
        bus1="ptes_inventory",
        efficiency=delivery * ptes["charge_efficiency"],
        p_nom=ptes["power_mw"] / delivery,
        marginal_cost=delivery
        * ((pump * adder if charge_pumping else 0) + (tariff if not system and owned else 0)),
        carrier="heat",
        **charge_extra,
    )
    n.add(
        "Link",
        "ptes_discharge",
        bus0="ptes_inventory",
        bus1="heat_htf",
        efficiency=ptes["discharge_efficiency"],
        p_nom=ptes["power_mw"] / ptes["discharge_efficiency"],
        marginal_cost=ptes["discharge_efficiency"]
        * (pump * adder + (0 if system else -discount + (0 if owned else tariff))),
        carrier="heat",
        **discharge_extra,
    )
    hp = config["heat_pumps"]
    for name in ["city2", "groundwater"]:
        spec = hp[name]
        cop = d[spec["cop_column"]]
        electrical_nominal = spec["capacity_mw"] / float(cop.min())
        maximum = spec["capacity_mw"] / (electrical_nominal * cop)
        committed = hp.get("policy", "endogenous") == "endogenous"
        if hp.get("policy", "endogenous") not in ("endogenous", "must_run"):
            raise ValueError("Heat pump policy must be endogenous or must_run")
        commitment = (
            {
                "min_up_time": hp["minimum_up_hours"],
                "min_down_time": hp["minimum_down_hours"],
                "up_time_before": 0,
                "down_time_before": hp["minimum_down_hours"],
                "start_up_cost": spec["capacity_mw"] * hp["startup_dkk_per_mw"],
            }
            if committed
            else {}
        )
        n.add(
            "Link",
            name,
            bus0="electricity",
            bus1="heat_htf",
            efficiency=cop,
            p_nom=electrical_nominal,
            p_max_pu=maximum,
            p_min_pu=maximum * (hp["minimum_fraction"] if committed else 1.0),
            committable=committed,
            marginal_cost=adder,
            carrier="heat",
            **commitment,
        )
    n.add("Load", "htf_demand", bus="heat_htf", p_set=d.htf_demand_mw)
    if not system:
        n.add(
            "Generator",
            "external_heat",
            bus="heat_cph",
            p_nom=2 * hx["capacity_mw"] + ptes["power_mw"],
            marginal_cost=0.0,
            carrier="heat",
        )
        if "efficiency2" in n.links:
            n.links["efficiency2"] = n.links.efficiency2.fillna(0.0)
        return n
    up = config["upstream"]
    residual = (
        d.regional_demand_mw - d.htf_demand_mw
        if config["demand_boundary"] == "assumed_gross_including_htf"
        else d.regional_demand_mw
    )
    if (residual < 0).any():
        raise ValueError("Regional demand smaller than HTF demand; check boundary, do not clip")
    n.add("Load", "other_regional_demand", bus="heat_cph", p_set=residual / delivery)
    for p in plants.itertuples(index=False):
        fuel_bus = p.name + "_fuel_bus"
        n.add("Bus", fuel_bus, carrier="fuel")
        n.add(
            "Generator",
            p.name + "_fuel",
            bus=fuel_bus,
            p_nom=p.fuel_mw * p.availability,
            marginal_cost=p.fuel_dkk_mwh,
            carrier="fuel",
        )
        if p.kind == "backpressure":
            heat_efficiency = p.eta_el / p.cm
            n.add(
                "Link",
                p.name + "_chp",
                bus0=fuel_bus,
                bus1="electricity",
                bus2="heat_cph",
                p_nom=p.power_mw / p.eta_el * p.availability,
                efficiency=p.eta_el,
                efficiency2=heat_efficiency,
                marginal_cost=heat_efficiency * p.vom_dkk_mwh_heat,
                carrier="heat",
            )
            if p.bypass_mw:
                # The field is EXTRA heat capacity, not the entire heat-only output.
                n.add(
                    "Link",
                    p.name + "_bypass",
                    bus0=fuel_bus,
                    bus1="heat_cph",
                    p_nom=(p.heat_mw + p.bypass_mw) / p.eta_bypass * p.availability,
                    efficiency=p.eta_bypass,
                    marginal_cost=p.eta_bypass * p.vom_dkk_mwh_heat,
                    carrier="heat",
                )
        else:
            # Joint links implement F=(P+Cv*Q)/eta_cond. Their opportunity-cost
            # heat coefficient is physical only with the backpressure constraint.
            n.add(
                "Link",
                p.name + "_power",
                bus0=fuel_bus,
                bus1="electricity",
                p_nom=p.power_mw / p.eta_el * p.availability,
                efficiency=p.eta_el,
                carrier="heat",
            )
            heat_efficiency = p.eta_el / p.cv
            n.add(
                "Link",
                p.name + "_heat",
                bus0=fuel_bus,
                bus1="heat_cph",
                p_nom=p.heat_mw / heat_efficiency * p.availability,
                efficiency=heat_efficiency,
                marginal_cost=heat_efficiency * p.vom_dkk_mwh_heat,
                carrier="heat",
            )
    for fuel in ["gas", "oil", "bio"]:
        efficiency = up[fuel + "_efficiency"]
        bus = fuel + "_supply_bus"
        n.add("Bus", bus, carrier="fuel")
        n.add(
            "Generator",
            fuel + "_fuel",
            bus=bus,
            p_nom=up[fuel + "_mw"] / efficiency,
            marginal_cost=up[fuel + "_dkk_mwh_fuel"],
            carrier="fuel",
        )
        n.add(
            "Link",
            fuel + "_boiler",
            bus0=bus,
            bus1="heat_cph",
            p_nom=up[fuel + "_mw"] / efficiency,
            efficiency=efficiency,
            marginal_cost=up["boiler_vom_dkk_mwh"] * efficiency,
            carrier="heat",
        )
    eta = up["electric_efficiency"]
    n.add(
        "Link",
        "electric_boiler",
        bus0="electricity",
        bus1="heat_cph",
        p_nom=up["electric_mw"] / eta,
        efficiency=eta,
        marginal_cost=up["electricity_adder_dkk_mwh"] + eta * up["boiler_vom_dkk_mwh"],
        carrier="heat",
    )
    n.add(
        "Link",
        "regional_hp",
        bus0="electricity",
        bus1="heat_cph",
        p_nom=up["heat_pump_mw"] / up["heat_pump_cop"],
        efficiency=up["heat_pump_cop"],
        marginal_cost=up["electricity_adder_dkk_mwh"],
        carrier="heat",
    )
    if up["waste_policy"] != "observed_upper_bound":
        raise ValueError("Only observed_upper_bound waste policy is supported")
    n.add("Bus", "waste_available", carrier="waste")
    n.add(
        "Generator",
        "waste_supply",
        bus="waste_available",
        p_nom=up["waste_capacity_mw"],
        carrier="waste",
    )
    n.add(
        "Link",
        "waste",
        bus0="waste_available",
        bus1="heat_cph",
        bus2="electricity",
        efficiency=1.0,
        efficiency2=up["waste_power_heat_ratio"],
        p_nom=up["waste_capacity_mw"],
        p_max_pu=np.minimum(d.waste_available_mw / up["waste_capacity_mw"], 1.0),
        marginal_cost=up["waste_vom_dkk_mwh_heat"],
        carrier="heat",
    )
    for name, spec in up["accumulators"].items():
        _storage(n, name, spec, "heat_cph", initial=spec["energy_mwh"] / 2)
    if "efficiency2" in n.links:
        n.links["efficiency2"] = n.links.efficiency2.fillna(0.0)
    return n


def _series(n, values):
    return xr.DataArray(np.asarray(values), coords={"snapshot": n.snapshots}, dims="snapshot")


def add_constraints(n, snapshots, *, relax=False, fixed_modes=None):
    """Add operational rules to the native network's Linopy model."""
    m, cfg = n.model, n._cph_config
    link = m["Link-p"]
    ptes = cfg["ptes"]
    c = link.sel(name="ptes_charge") * n._cph_delivery
    d = link.sel(name="ptes_discharge") * ptes["discharge_efficiency"]
    h = link.sel(name="hx") * n._cph_delivery
    integer = cfg["integer_operation"] and not relax
    bounds = {"binary": True} if integer else {"lower": 0.0, "upper": 1.0}
    yc = m.add_variables(coords=[n.snapshots], name="ptes_charge_on", **bounds)
    yd = m.add_variables(coords=[n.snapshots], name="ptes_discharge_on", **bounds)
    for label, flow, status, minimum in [
        ("charge", c, yc, ptes["min_charge_mw"]),
        ("discharge", d, yd, ptes["min_discharge_mw"]),
    ]:
        m.add_constraints(flow <= ptes["power_mw"] * status, name="ptes_" + label + "_maximum")
        m.add_constraints(flow >= minimum * status, name="ptes_" + label + "_minimum")
        m.add_constraints(
            flow.diff("snapshot") <= ptes["ramp_mw_h"], name="ptes_" + label + "_ramp_up"
        )
        m.add_constraints(
            flow.diff("snapshot") >= -ptes["ramp_mw_h"], name="ptes_" + label + "_ramp_down"
        )
        m.add_constraints(
            flow.isel(snapshot=0) <= ptes["ramp_mw_h"], name="ptes_" + label + "_initial_idle"
        )
    m.add_constraints(yc + yd <= 1, name="ptes_exclusive")
    for lag in range(1, min(ptes["reversal_hours"] + 1, len(snapshots))):
        for name, a, b in [("cd", yc, yd), ("dc", yd, yc)]:
            future = b.isel(snapshot=slice(lag, None)).assign_coords(snapshot=n.snapshots[:-lag])
            m.add_constraints(
                a.isel(snapshot=slice(None, -lag)) + future <= 1,
                name=f"ptes_no_reversal_{name}_{lag}",
            )
    m.add_constraints(h + c <= cfg["hx"]["capacity_mw"], name="shared_htf_connection")
    m.add_constraints(
        m["Store-e"].sel(name="ptes").isel(snapshot=-1) == ptes["terminal_mwh"],
        name="ptes_terminal",
    )
    if cfg["heat_pumps"].get("policy", "endogenous") == "endogenous":
        on, start, stop = [m[k] for k in ["Link-status", "Link-start_up", "Link-shut_down"]]
        m.add_constraints(
            on.isel(snapshot=0) - start.isel(snapshot=0) + stop.isel(snapshot=0) == 0,
            name="hp_initial_off_transition",
        )
        current = n.snapshots[1:]
        previous = on.isel(snapshot=slice(None, -1)).assign_coords(snapshot=current)
        m.add_constraints(
            on.isel(snapshot=slice(1, None))
            - previous
            - start.isel(snapshot=slice(1, None))
            + stop.isel(snapshot=slice(1, None))
            == 0,
            name="hp_exact_transition",
        )
        m.add_constraints(start + stop <= 1, name="hp_one_transition")
        for event, duration, label in [
            (start, cfg["heat_pumps"]["minimum_up_hours"], "start"),
            (stop, cfg["heat_pumps"]["minimum_down_hours"], "stop"),
        ]:
            if duration > 1:
                m.add_constraints(
                    event.isel(snapshot=slice(-(duration - 1), None)) == 0, name="hp_end_" + label
                )
    response = cfg["objective"] == "local" and cfg["settlement_boundary"] == "discharge_service"
    if response or n._cph_fixed_local is not None:
        planned = _series(n, n._cph_inputs.scheduled_ptes_charge_mw)
        if cfg.get("response", {}).get("charging_policy", "curtailable") == "fixed":
            m.add_constraints(c == planned, name="fixed_central_charging")
        else:
            m.add_constraints(c <= planned, name="announced_charging_availability")
    if cfg["objective"] == "system":
        peak = sum(
            link.sel(name=f + "_boiler") * cfg["upstream"][f + "_efficiency"]
            for f in ["gas", "oil", "bio", "electric"]
        )
        m.add_constraints(peak <= cfg["upstream"]["shared_peak_mw"], name="shared_peak_capacity")
        for p in n._cph_plants.itertuples():
            if p.kind == "backpressure":
                q = link.sel(name=p.name + "_chp") * p.eta_el / p.cm
                if p.name + "_bypass" in n.links.index:
                    q = q + link.sel(name=p.name + "_bypass") * p.eta_bypass
            else:
                q = link.sel(name=p.name + "_heat") * p.eta_el / p.cv
                power = link.sel(name=p.name + "_power") * p.eta_el
                m.add_constraints(power >= p.cm * q, name=p.name + "_backpressure_limit")
            m.add_constraints(
                q <= (p.heat_mw + p.bypass_mw) * p.availability,
                name=p.name + "_total_heat_capacity",
            )
        for name, spec in cfg["upstream"]["accumulators"].items():
            m.add_constraints(
                link.sel(name=name + "_charge") + link.sel(name=name + "_discharge")
                <= spec["power_mw"],
                name=name + "_shared_converter",
            )
            m.add_constraints(
                m["Store-e"].sel(name=name).isel(snapshot=-1) == spec["energy_mwh"] / 2,
                name=name + "_terminal",
            )
    if n._cph_fixed_local is not None:
        fixed = n._cph_fixed_local
        for expr, column in [(h, "hx_mw"), (d, "ptes_discharge_mw")]:
            m.add_constraints(expr == _series(n, fixed[column]), name="actual_" + column)
        for name in ["city2", "groundwater"]:
            cop = _series(n, n._cph_inputs[cfg["heat_pumps"][name]["cop_column"]])
            m.add_constraints(
                link.sel(name=name) * cop == _series(n, fixed[name + "_heat_mw"]),
                name="actual_" + name,
            )
    for name, values in (fixed_modes or {}).items():
        m.add_constraints(m[name] == values, name="fixed_mode_" + name)


def _optimise(n, *, relax=False, fixed_modes=None):
    cfg = n._cph_config
    n.optimize.create_model(linearized_unit_commitment=relax or not cfg["integer_operation"])
    add_constraints(n, n.snapshots, relax=relax, fixed_modes=fixed_modes)
    settings = cfg["solver"]
    backend = settings.get("backend", "highs")
    if backend == "highs":
        options = {
            "time_limit": settings["time_limit"],
            "mip_rel_gap": settings["mip_rel_gap"],
            "threads": settings.get("threads", 4),
        }
    elif backend == "gurobi":
        options = {
            "TimeLimit": settings["time_limit"],
            "MIPGap": settings["mip_rel_gap"],
            "Threads": settings.get("threads", 4),
            "OutputFlag": 0,
        }
    else:
        raise ValueError("Unknown solver backend")
    status, condition = n.optimize.solve_model(
        solver_name=backend, solver_options=options, io_api="direct", log_to_console=False
    )
    if status != "ok" or condition != "optimal":
        raise RuntimeError(f"No accepted solution: {status}/{condition}")
    return n


def feasibility(n):
    """Evaluate every active Linopy constraint and bound independently of solver status."""
    maximum = 0.0
    for name, constraint in n.model.constraints.items():
        lhs, rhs = constraint.lhs.solution.values, constraint.rhs.values
        mask = constraint.labels.values >= 0
        error = lhs - rhs
        signs = constraint.sign.values
        violation = np.where(signs == "=", np.abs(error), np.where(signs == "<=", error, -error))
        if not np.isfinite(violation[mask]).all():
            raise RuntimeError("Non-finite active constraint: " + name)
        maximum = max(maximum, float(np.maximum(violation[mask], 0).max(initial=0)))
    bound_error, integer_error = 0.0, 0.0
    for _, variable in n.model.variables.items():
        values = variable.solution.values
        mask = variable.labels.values >= 0
        violation = np.maximum(variable.lower.values - values, values - variable.upper.values)
        bound_error = max(bound_error, float(np.maximum(violation[mask], 0).max(initial=0)))
        if variable.attrs.get("binary", False) or variable.attrs.get("integer", False):
            integer_error = max(
                integer_error, float(np.abs(values[mask] - np.rint(values[mask])).max(initial=0))
            )
    if max(maximum, bound_error, integer_error) > 1e-5:
        raise RuntimeError("Solver result failed independent feasibility check")
    return {
        "max_constraint_violation": maximum,
        "max_bound_violation": bound_error,
        "max_integer_violation": integer_error,
    }


def conditional_prices(n, solution=None):
    """Resolve a continuous PyPSA/Linopy model with accepted integer decisions fixed."""
    if n._cph_config["objective"] != "system":
        raise ValueError("Upstream marginal values require the system objective")
    if not n._cph_config["integer_operation"]:
        n._cph_conditional_bus_prices = n.buses_t.marginal_price.copy()
        return n.buses_t.marginal_price.heat_cph.to_numpy()
    names = [
        "ptes_charge_on",
        "ptes_discharge_on",
        "Link-status",
        "Link-start_up",
        "Link-shut_down",
    ]
    modes = (
        {
            name: n.model[name].solution.copy(deep=True)
            for name in names
            if name in n.model.variables
        }
        if n._cph_config["integer_operation"]
        else {}
    )
    price_network = build(
        n._cph_inputs, n._cph_config, n._cph_plants, fixed_local=n._cph_fixed_local
    )
    _optimise(price_network, relax=True, fixed_modes=modes)
    feasibility(price_network)
    n._cph_conditional_bus_prices = price_network.buses_t.marginal_price.copy()
    return price_network.buses_t.marginal_price.heat_cph.to_numpy()


@dataclass
class Solution:
    network: pypsa.Network
    dispatch: pd.DataFrame
    summary: dict
    raw: object


def solve(n, *, prices=False):
    _optimise(n)
    checks = feasibility(n)
    dispatch = collect(n)
    summary = summarise(n, dispatch)
    summary.update(checks)
    if prices:
        dispatch["conditional_upstream_value_dkk_mwh"] = conditional_prices(n)
        summary["price_method"] = (
            "Continuous PyPSA/Linopy solve with all commitment decisions fixed"
        )
        n.buses_t.marginal_price = n._cph_conditional_bus_prices.copy()
        n.meta["price_method"] = summary["price_method"]
    elif n._cph_config["integer_operation"]:
        n.buses_t.marginal_price.loc[:, :] = np.nan
        n.meta["price_method"] = (
            "No raw MILP duals reported; use --prices for a fixed-commitment LP"
        )
    else:
        n.meta["price_method"] = "Continuous dispatch LP"
    n.meta["solver_status"] = summary["solver_status"]
    n.meta["objective_dkk"] = summary["objective_dkk"]
    n.meta["response_charging_policy"] = n._cph_config.get("response", {}).get(
        "charging_policy", "curtailable"
    )
    return Solution(n, dispatch, summary, SimpleNamespace(fun=n.objective, success=True))
