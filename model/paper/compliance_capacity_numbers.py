"""Numbers for the full-compliance and discharge-capacity results.

Usage: python compliance_capacity_numbers.py <base_30mw_study> <compliance_30mw_study> <d23_study> <output.json>
The base study supplies the 30 MW hourly-credit case; the others the new cases.
"""

import json
import sys
from pathlib import Path

import pandas as pd

base, compliance, d23, output = (Path(p) for p in sys.argv[1:5])


def load(study):
    table = pd.read_csv(study / "study.csv")
    table["week"] = table.scenario.str.split("__").str[0]
    gap = table.combined_system_solver_gap_bound_dkk
    table["both_win"] = (table.local_bill_saving_dkk >= -gap) & (
        table.aggregate_upstream_operating_surplus_change_dkk >= -gap
    )
    return table


def summary(table):
    reference = table[table.tariff == "reference"]
    coordinated_cost = (
        reference.corrective_system_cost_dkk - reference.system_cost_change_from_coordinated_dkk
    ).sum()
    central_discharge = sum(
        pd.read_csv(path).ptes_discharge_mw.sum()
        for path in sorted(Path(table.attrs["dir"]).glob("w*__*/central/dispatch.csv"))
    )
    result = {
        "coordination_value_mdkk": reference.system_cost_change_from_coordinated_dkk.sum() / 1e6,
        "coordinated_cost_mdkk": coordinated_cost / 1e6,
        "reference_cost_mdkk": reference.corrective_system_cost_dkk.sum() / 1e6,
        "coordinated_discharge_gwh": central_discharge / 1e3,
        "cases": {},
    }
    for tariff, rows in table.groupby("tariff"):
        result["cases"][tariff] = {
            "system_saving_mdkk": rows.system_operating_cost_saving_dkk.sum() / 1e6,
            "htf_saving_mdkk": rows.local_bill_saving_dkk.sum() / 1e6,
            "upstream_gain_mdkk": rows.aggregate_upstream_operating_surplus_change_dkk.sum() / 1e6,
            "heat_revenue_change_mdkk": rows.supplier_local_heat_revenue_change_dkk.sum() / 1e6,
            "discharge_gwh": rows.ptes_discharge_mwh.sum() / 1e3,
            "cycles": rows.ptes_discharge_mwh.sum() / 3300,
            "weeks_htf_gain": int((rows.local_bill_saving_dkk >= -rows.combined_system_solver_gap_bound_dkk).sum()),
            "weeks_both_win": int(rows.both_win.sum()),
            "recovered_share": rows.system_operating_cost_saving_dkk.sum()
            / reference.system_cost_change_from_coordinated_dkk.sum(),
        }
    return result


numbers = {}
for name, path in [("base_30mw", base), ("compliance_30mw", compliance), ("d23", d23)]:
    table = load(path)
    table.attrs["dir"] = str(path)
    numbers[name] = summary(table)
numbers["value_of_30mw_vs_23mw_mdkk"] = (
    numbers["d23"]["coordinated_cost_mdkk"] - numbers["base_30mw"]["coordinated_cost_mdkk"]
)
output.write_text(json.dumps(numbers, indent=2))
print(json.dumps(numbers, indent=2))
