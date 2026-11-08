# Configuration index

The canonical model uses `base.yaml` and `plants.csv`. Current defaults are Gurobi,
eight threads, 30 MW delivered charging/discharging and provisional pumping of
0.005 MWh electricity per charged/discharged MWh. `asset_provenance.json` records
the plant transcription sources. The legacy input provenance is in `data/legacy/`.

| Study configuration | Purpose and evidence status |
|---|---|
| `tariff_findings_30mw.yaml` | **Current findings**: matched constant/hourly discounts, three 168-hour periods, fixed direct-heat tariff |
| `tariff_findings_lossless_30mw.yaml` | **Current sensitivity**: identical experiment with PTES standing loss set to zero |
| `marginal_price_pilot.yaml` | Exploratory absolute heat/inventory-value pricing; archived outputs used 23 MW charging, so use fresh outputs for a 30/30 MW rerun |
| `tariff_pilot.yaml` | Exploratory 0.003-pumping sensitivity; archived outputs are not the current 0.005 main case |
| `tariff_smoke.yaml` | Small explicitly synthetic methodology check |
| `tariff_study.yaml` | Wider sensitivity design; not executed in full |

Keep physical settings matched within each comparison. Configuration names describe
experiments, not proven contractual rates. Do not edit `base.yaml` to reproduce a
historical run: use that run's saved assumptions/inputs or an explicit configuration.
