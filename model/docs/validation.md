# Current validation and evidence

## Current configuration

Gurobi with eight threads; PTES delivered charging/discharging limits both 30 MW;
provisional pumping 0.005 MWh electricity per charged/discharged MWh. Physical and
financial assumptions are stated in [the formulation](formulation.md). Changing
configuration is not evidence of an annual or empirically calibrated result.

## Automated checks

The suite covers heat/electricity balances, CHP shared fuel/extraction regions and
full bypass capability, first-hour storage losses, PTES modes/minima/ramps/reversals,
30 MW charging/discharging, HP thermal limits/commitment, non-unit efficiencies,
zero-COP availability, tariff transfers, corrective local-decision fixing, conditional
value finite differences, bounded/monthly-mean tariff construction, data repair and
UTC/DST rules, legacy temperature/COP parity and failure without partial publication.
Optional Gurobi/HiGHS equivalence requires a usable Gurobi licence; portable fixtures
use HiGHS. CI explicitly selects HiGHS for its smoke commands while research runs
retain Gurobi.

Latest local cleanup check: **26 tests passed**, including licensed Gurobi/HiGHS
equivalence. Ruff lint, Ruff formatting and whitespace checks passed. Both CI smoke
commands (48-hour demo with conditional prices and 24-hour synthetic comparison)
completed with their explicitly selected HiGHS backend. These are local executions
of the CI commands, not a claim that a new remote CI run has completed.

Run from `model/`:

```sh
ruff check src tests
ruff format --check src tests
pytest -q
```

## Current research evidence

The [versioned snapshot](../reports/selected_weeks_30mw/README.md) contains the base
and zero-PTES-standing-loss tables/figures, complete tested tariff families, executed
specifications, assumptions and input/runtime fingerprints. Full accepted local
runs are listed in [the result index](../results/README.md).

Both studies use Gurobi and the corrected 30/30 MW limits with pumping 0.005 per flow.
All candidate energy/cost differences were independently reconciled (residuals below
1e-5 MWh and 1e-4 DKK). The compact evidence keeps the unsuccessful participation
cases as well as positive results. Error bars are corrective solver-gap bounds,
not statistical confidence intervals or forecast/input uncertainty. Reference
against itself has zero difference and a zero displayed error bar.

The selected-week findings and mechanisms are described in [findings_30mw.md](findings_30mw.md).
The historical annual audit identifies SOC-difference proxies, not independent
metered charge/discharge. Annual operating benefits, actual behavioural response,
individual supplier profit and a calibrated optimal contractual tariff remain
unestablished. Do not extrapolate the selected weeks to a yearly result.

## Historical checks

The complete pre-cleanup [validation record](history/validation_before_cleanup_2026-11-08.md)
preserves the earlier 23 MW, 23/30 MW, zero-pumping and 0.003-pumping diagnostics,
solver equivalence and original annual LP/runtime observations. Its original run
paths are resolved through `results/archive/2026-11-08/index.json` locally. The
archive retains original metadata and hashes; historical results are not relabelled
as current 30/30 MW evidence.

[validation_inputs.json](validation_inputs.json) and
[validation_metrics.json](validation_metrics.json) are retained historical provenance
records, not updated annual results. Legacy root inputs/scripts/outputs are preserved.
