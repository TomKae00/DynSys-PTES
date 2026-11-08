# Local result index

Full run directories are generated and ignored by Git. The compact, versioned
[results snapshot](../reports/selected_weeks_30mw/README.md) contains the current
tables, figures, assumptions and provenance that travel with the branch.

## Current accepted experiments

| Directory | Role |
|---|---|
| `findings_30_30_pump005/` | Three selected 2024 weeks, Gurobi, 30 MW each direction, pumping 0.005 per flow; all constant/hourly controls |
| `findings_30_30_pump005_lossless/` | Matched zero-PTES-standing-loss sensitivity; regional losses remain |
| `findings_30_30_paper/` | Combined PDF/SVG/PNG figures, figure tables and reconciled evidence |
| `annual_2024_reference_audit/` | Historical SOC-proxy audit; not an annual economic result |

These are selected-week scenario results, not a calibrated annual welfare estimate.
See [findings and limitations](../docs/findings_30mw.md).

## Inputs and historical runs

Weather-derived temperature/COP profiles live in
`../data/processed/profiles_2024/`, alongside the prepared annual inputs.

Earlier pilots, synthetic diagnostics, pre-30/30 MW runs and redundant figures
are preserved under `archive/2026-11-08/`. The archive's `index.json` records their
original/current locations, inventories and hashes. Original solve metadata and
embedded paths are left unchanged. Root-level `../../results/` contains the older
model's tracked outputs and is preserved as legacy material.

Use a **fresh output directory** for a new solve. The CLI refuses to overwrite
accepted results; do not confuse a later exploratory run with this snapshot.
