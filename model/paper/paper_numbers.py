"""All numbers quoted in the paper's results, from one weekly study directory.

Usage: python paper_numbers.py <study_dir> <varmelast_2024_hourly.csv> <output.json>
"""

import json
import sys
from pathlib import Path

import pandas as pd

study, observed_path, output = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
table = pd.read_csv(study / "study.csv")
table["week"] = table.scenario.str.split("__").str[0]
gap = table.combined_system_solver_gap_bound_dkk
table["both_win"] = (table.local_bill_saving_dkk >= -gap) & (
    table.aggregate_upstream_operating_surplus_change_dkk >= -gap
)
reference = table[table.tariff == "reference"].set_index("week")
coordination = reference.system_cost_change_from_coordinated_dkk.sum()


def read(week, case):
    return pd.read_csv(study / f"{week}__base" / case / "dispatch.csv", parse_dates=["timestamp"])


weeks = sorted(table.week.unique())
central = pd.concat(read(w, "central") for w in weeks)
measured = pd.concat(read(w, "metered_corrective") for w in weeks)
hourly = pd.concat(read(w, "hourly_5_g025_corrective") for w in weeks)
hp = lambda d: (d.city2_heat_mw + d.groundwater_heat_mw).sum() / 1e3  # noqa: E731

numbers = {
    "weeks": len(weeks),
    "coordination_value_mdkk": coordination / 1e6,
    "max_reconciliation_residual_dkk": float(table.stakeholder_reconciliation_residual_dkk.abs().max()),
    "discharge_gwh": {
        "coordinated": central.ptes_discharge_mw.sum() / 1e3,
        "measured": measured.ptes_discharge_mw.sum() / 1e3,
    },
    "hp_heat_gwh": {"coordinated": hp(central), "measured": hp(measured), "hourly": hp(hourly)},
    "tariffs": {},
}
for tariff, rows in table.groupby("tariff"):
    numbers["tariffs"][tariff] = {
        "system_saving_mdkk": rows.system_operating_cost_saving_dkk.sum() / 1e6,
        "htf_saving_mdkk": rows.local_bill_saving_dkk.sum() / 1e6,
        "upstream_gain_mdkk": rows.aggregate_upstream_operating_surplus_change_dkk.sum() / 1e6,
        "heat_revenue_change_mdkk": rows.supplier_local_heat_revenue_change_dkk.sum() / 1e6,
        "discharge_gwh": rows.ptes_discharge_mwh.sum() / 1e3,
        "cycles": rows.ptes_discharge_mwh.sum() / 3300,
        "weeks_both_win": int(rows.both_win.sum()),
        "recovered_share": rows.system_operating_cost_saving_dkk.sum() / coordination,
        "solver_gap_mdkk": rows.combined_system_solver_gap_bound_dkk.sum() / 1e6,
    }

# Validation: modelled production in the measured-2024 reference vs Varmelast 2024.
observed = pd.read_csv(observed_path, parse_dates=["timestamp_utc"]).set_index("timestamp_utc")
model = measured.set_index("timestamp")
model.index = model.index.tz_convert("UTC")
obs = observed.loc[observed.index.intersection(model.index)]
model = model.loc[obs.index]
chp = sum(model[f"{p}_heat_mw"] for p in ["AMV1", "AMV4", "AVV1", "AVV2", "KKV8"])
numbers["validation_twh"] = {
    "CHP": [chp.sum() / 1e6, obs.chp_MW.sum() / 1e6],
    "Waste incineration": [model.waste_heat_mw.sum() / 1e6, obs.waste_to_energy_MW.sum() / 1e6],
    "Peak boilers": [
        sum(model[f"{f}_boiler_heat_mw"] for f in ["gas", "oil", "bio"]).sum() / 1e6,
        (obs.peak_gas_MW + obs.peak_oil_MW + obs.peak_biomass_MW).sum() / 1e6,
    ],
    "Electric boilers and heat pumps": [
        (model.electric_boiler_heat_mw + model.regional_hp_heat_mw).sum() / 1e6,
        (obs.electric_boilers_MW + obs.heat_pumps_MW).sum() / 1e6,
    ],
    "Other (surplus heat, biogas, solar)": [
        0.0,
        (obs.industrial_surplus_heat_MW + obs.data_centre_surplus_heat_MW + obs.biogas_MW + obs.solar_thermal_MW).sum() / 1e6,
    ],
}
numbers["validation_hours"] = len(obs)
numbers["validation_chp_hourly_correlation"] = float(chp.corr(obs.chp_MW))
output.write_text(json.dumps(numbers, indent=2))
print(json.dumps(numbers, indent=2))
