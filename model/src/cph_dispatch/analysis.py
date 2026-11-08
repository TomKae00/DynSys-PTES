"""Reconcile the physical mechanism and costs across two matched corrective cases."""

import numpy as np


def reconcile(reference, candidate, reference_summary, candidate_summary):
    if not reference.index.equals(candidate.index):
        raise ValueError("Mechanism reconciliation requires exactly matched snapshots")
    cfg = reference_summary["assumptions"]
    if cfg["network_loss_fraction"] != candidate_summary["assumptions"]["network_loss_fraction"]:
        raise ValueError("Compare tariffs within a common physical scenario")
    for column in ["regional_demand_mw", "htf_demand_mw"]:
        if not np.allclose(reference[column], candidate[column], atol=1e-8):
            raise ValueError("Mechanism reconciliation needs matched demand")
    r = 1 - cfg["network_loss_fraction"]
    avoided_ptes = sum(
        float(reference[k].sum() - candidate[k].sum())
        for k in ["ptes_standing_loss_mwh", "ptes_conversion_loss_mwh"]
    )
    hp = sum(
        float(candidate[k].sum() - reference[k].sum())
        for k in ["city2_heat_mw", "groundwater_heat_mw"]
    )
    inventory = float(reference.ptes_energy_mwh.iloc[-1] - candidate.ptes_energy_mwh.iloc[-1])
    inventory -= (
        cfg["ptes"]["initial_mwh"] - candidate_summary["assumptions"]["ptes"]["initial_mwh"]
    )
    regional_loss = sum(
        float(reference[s + "_standing_loss_mwh"].sum() - candidate[s + "_standing_loss_mwh"].sum())
        for s in cfg["upstream"]["accumulators"]
    )
    regional_inventory = sum(
        float(reference[s + "_energy_mwh"].iloc[-1] - candidate[s + "_energy_mwh"].iloc[-1])
        for s in cfg["upstream"]["accumulators"]
    )
    # Regional inventories start at half configured capacity.
    regional_inventory -= sum(
        (
            spec["energy_mwh"]
            - candidate_summary["assumptions"]["upstream"]["accumulators"][s]["energy_mwh"]
        )
        / 2
        for s, spec in cfg["upstream"]["accumulators"].items()
    )
    actual = float(
        reference.upstream_heat_production_mw.sum() - candidate.upstream_heat_production_mw.sum()
    )
    predicted = (avoided_ptes + hp + inventory) / r + regional_loss + regional_inventory
    cost = {
        k: reference_summary["operating_cost_breakdown_dkk"][k]
        - candidate_summary["operating_cost_breakdown_dkk"][k]
        for k in reference_summary["operating_cost_breakdown_dkk"]
    }
    saving = reference_summary["objective_dkk"] - candidate_summary["objective_dkk"]
    return {
        "avoided_upstream_production_mwh": actual,
        "ptes_loss_reduction_delivered_mwh": avoided_ptes,
        "additional_local_hp_heat_mwh": hp,
        "ptes_inventory_change_difference_mwh": inventory,
        "regional_standing_loss_reduction_mwh": regional_loss,
        "regional_inventory_change_difference_mwh": regional_inventory,
        "production_reconciliation_residual_mwh": actual - predicted,
        "operating_saving_by_cost_component_dkk": cost,
        "cost_reconciliation_residual_dkk": saving - sum(cost.values()),
        "interpretation": "Operating savings under scenario costs/adders, not a full welfare estimate",
    }
