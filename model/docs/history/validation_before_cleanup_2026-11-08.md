# Historical record retained during cleanup

Original run paths below refer to superseded local experiments. Consult
`model/results/archive/2026-11-08/index.json` for their current locations.
The current [validation summary](../validation.md) and [results snapshot](../../reports/selected_weeks_30mw/README.md)
are the entry points for the corrected 30/30 MW study.

# PyPSA validation record — 5 November 2026

**Current capacity correction:** the default now permits **30 MW charging and
30 MW discharging**, measured as delivered heat. Earlier runs below with 23 MW
charging retain that assumption in their saved metadata and must be rerun for a
symmetric 30 MW comparison. Historical fixtures explicitly retain their old limits.

This is the retained historical record for the original 23 MW scenario. See the
[8 November update](#htf-tariff-workflow-and-30-mw-discharge--8-november-2026) below
for the current configuration, additional tests and Gurobi runs.

These checks validate the implementation and numerical feasibility. They do not
establish empirical calibration, actual operator behaviour or an optimal tariff.
[validation_inputs.json](../validation_inputs.json) records source hashes and each data
repair; [validation_metrics.json](../validation_metrics.json) records the executed cases.

## Framework and regression checks

All 17 tests passed in a complete local run. The clean CI run is tracked on the PR.
Gurobi 13.0.3 was available locally; its 8-hour comparison with HiGHS passed. That
optional test is skipped in the default HiGHS-only environment.

The tests cover both heat balances, common CHP fuel limits, extraction regions,
correct full bypass heat capacity, PTES inventory/power/minimum/ramp/reversal rules,
HP commitment and thermal ceilings under changing COP, common inventory endpoints,
financial transfers, data repairs, UTC/DST alignment, CLI failure without result
export, and actual upstream corrective dispatch. A saved network is reloaded with
PyPSA and checked for inventory, custom status and conditional bus-price data.
A non-unit charge/discharge efficiency case checks storage losses and the full
native electricity balance, including pumping and generation exports.

Three 24-hour objectives agree with the former direct formulation within 0.1 DKK:
coordinated dispatch, the legacy owned-store calculation, and fixed-charge discharge
settlement. Bypass is disabled in that fixture to isolate framework equivalence.
The reference commit and numbers are pinned in tests/fixtures/direct_reference.json.
The former bypass implementation incorrectly capped the whole heat-only mode at
its extra heat capacity. The new, separately tested AMV4 design point reaches
550 MW heat from 487 MW fuel, with no electricity output and shared fuel limits.
The explicit first-hour storage-loss loads preserve the direct formulation's
physical initial-inventory convention despite PyPSA's different native convention.

## Public 2024 data

Preparation covers 8784 unique consecutive UTC hours of the Danish calendar year.
The opt-in repair policy logged 87 cells: 41 CTR, 43 VEKS and 3 waste values. This
includes the 39-hour consumption outage and missing repeated autumn-clock hour.
Raw files are cached with query metadata and hashes. Inherited local demand remains
a 2019 seasonal template; modeled COP and monthly reference prices are not verified
2024 observations or contracts. The CTR/VEKS/HTF metering boundary and 2% network
loss assumption still require validation.

## Executed PyPSA cases

| Case | Hours | Net operating objective DKK | Relative MILP gap | Maximum constraint residual |
|---|---:|---:|---:|---:|
| Winter, 8–14 January UTC | 168 | 30,155,992.34 | 0.00000409 | < 1e-8 |
| Summer, 15–21 July UTC | 168 | −16,761,010.46 | 0.000000579 | < 1e-8 |
| Full-year LP relaxation | 8784 | −249,925,959.49 | 0 | < 1e-8 |

Each accepted case exported a native network.nc, dispatch.csv and summary.json.
Seasonal MILPs also resolved conditional LP marginal values with commitments fixed.
The annual LP has 430,416 variables and 1,141,919 constraints. Its relaxed modes
must not be presented as an integer PTES operating schedule. Negative objectives
include electricity revenue and condensing generation; they are not observed
negative heat tariffs or a calibrated social resource-cost measure.

An annual integer attempt used a 60-second solver setting and an external
150-second process limit. The external budget expired without an accepted export.
No full-year MILP schedule, price calculation or Gurobi annual result is claimed.
A longer research solve with a suitable licence remains necessary. Solver time
limits are not strict process wall limits, and timeout is not proof of infeasibility.

## Coupled response checks

Both a synthetic 48-hour comparison and a 48-hour public-input winter comparison
completed the five-solve sequence: central, reference local/corrective, and candidate
local/corrective. They exported five networks and separate financial/system metrics.
In the public-input example, the supplied constant 50 DKK/MWh credit reduced the
local bill by about 25,088 DKK and corrective system expenditure by about 1,062 DKK.
These are scenario diagnostics, not a calibrated tariff recommendation. Local bill
savings and system savings differ; supplier local heat revenue is not profit.

The default zero pumping assumption can leave the zero-credit local response
indifferent between discharge and direct supply. Its selected throughput must not
be treated as a prediction of HTF behaviour. A controlled regression case therefore
uses an explicitly assumed positive pumping coefficient and a smaller store: the
reference chooses negligible discharge, the credit case discharges, and upstream
charging is curtailed/re-optimised with the same final inventory. This demonstrates
that the new formulation permits lower utilisation; it does not estimate real
behaviour or pumping consumption.

Curtailable charging is an explicit analytical assumption about upstream adaptation
within the announced charging ceiling. Actual H, D and local HP heat are fixed in
corrective dispatch; its charging/inventory trajectory is authoritative. Electricity
adjustments are valued at the same exogenous DK2 prices, without actual balancing-
market settlement. Financial differences are reported with solver gap bounds.

## Remaining scientific work

Confirm metering and settlement boundaries, actual plant availability, costs, waste
throughput/must-take treatment, HP operating profiles, network losses and pumping.
Validate against independent measured production and PTES flows. Test 23/30 MW and
asymmetric charge/discharge ratings, losses, HP policies and horizon endpoints.
Derive the tariff rather than only supply a candidate; add behavioural preferences,
deviation/imbalance settlement, rolling forecasts and repeated feedback where needed.

## Repository transfer

The validated implementation and numerical records were transferred from
`TomKae00/DynSys-Dynamic-Tariff` at `17c8261c10ad5fc8f31ca41464078f95959b360b` into
`TomKae00/DynSys-PTES`. The model source, configuration and tests are identical;
only repository navigation and provenance notes were adjusted. CI runs separately
in the destination repository.

## HTF tariff workflow and 30 MW discharge — 8 November 2026

Current research solver: **Gurobi 13.0.3, eight threads**. Current delivered PTES
limits: **23 MW charging, 30 MW discharge**, with separate optional overrides.
The host-bound Gurobi licence is available outside this environment's sandbox;
inside it, Gurobi reports a host-ID mismatch. No automatic solver fallback was
added. Tests use portable HiGHS fixtures and explicitly compare the Gurobi backend.

Executed verification: **25 tests passed**, including the licensed Gurobi/HiGHS
comparison. Ruff and `git diff --check` passed. Additional tests compare a full
leap-year temperature/COP calculation against the original scripts, exercise UTC
warm-up/edge-hour rejection, preserve zero-COP cutoffs/HP unavailability, reach
30 MW delivered discharge with charging bounded at 23 MW, reject SOC proxies as
metered flows, validate the value-spread sign by paired boundary perturbation,
and reconcile physical/financial differences and reference-throughput extrema.
The pinned original direct-formulation fixture explicitly retains 23 MW discharge.

Regenerated weather-based profiles cover 8,784 Danish-calendar hours and agree
with the original COP file on common true UTC timestamps within `5e-15`.
No original scripts or existing result folders were overwritten.

The original Gurobi 23 MW winter coordinated objective was reproduced exactly:
30,155,869.977557 DKK. New accepted runs:

| Run under `model/results/` | Purpose |
|---|---|
| `review_winter_gurobi_30mw` | 168-hour Gurobi coupled comparison, inherited COP/template inputs, 50 DKK/MWh credit, conditional values and reference range |
| `review_winter_gurobi_30mw_figures` | Model/recorded-inventory context, source CSVs and cost/loss reconciliation |
| `review_tariff_pilot_gurobi_30mw` | Three 168-hour weeks, actual UTC weather-derived COPs, assumed pumping 0.003, zero/5/50/mean-matched hourly credit |
| `review_tariff_verified` | Explicitly synthetic methodology check, before the requested change to the default discharge limit |

The 30 MW winter coordinated objective is 30,154,737.622148 DKK. The illustrative
50-credit comparison saves 17,139.70 DKK operating expenditure and 74,462.46 DKK
HTF expenditure, implying **-57,322.76 DKK** change in the hypothetical aggregate
upstream account. Combined corrective gap: 236.09 DKK. Zero-pumping reference
throughput spans 0–1,489.25 MWh within 0.01 DKK of accepted HTF expenditure under
that run's charging ceiling. This ambiguity is distinct from the corrective gap.

The three-week 30 MW pilot uses **assumed** pumping and corrected UTC COP alignment;
it is a separate scenario from the zero-pumping winter reproduction. For a constant
5 DKK/MWh credit, versus its matched zero-credit reference:

| Week | Operating saving DKK | HTF bill saving DKK | Aggregate upstream surplus change DKK | Combined corrective gap DKK |
|---|---:|---:|---:|---:|
| Winter | 7,335.52 | 3,685.77 | 3,649.75 | 291.65 |
| Shoulder | 85,207.55 | 6,119.51 | 79,088.04 | <0.01 |
| Summer | 9,792.69 | 2,326.88 | 7,465.80 | 15.76 |

The hourly mean-matched 5-credit candidate has lower system cost than constant 5
in each tested week, but in winter it makes the aggregate upstream account worse
off. A 50-credit candidate also makes that account worse off in winter and summer.
Aggregate stakeholder reconciliation residuals are below `2.8e-10 DKK`. These are
conditional scenario findings, not confirmed supplier profit, societal welfare,
observed behaviour or a recommended tariff. Arithmetic mean matching does not
hold volume-weighted revenue constant.

The full parameter design in `config/tariff_study.yaml` is supplied but has not
been executed in full. Metered pumping/flows, actual local demand, contractual
allocation and operating restrictions still require evidence. Full-year integer
dispatch, rolling horizons and actual balancing settlement remain unimplemented
or unverified as stated in the historical record. See the
[research audit](../research_workflow.md) for model boundaries and the derivation.

### Absolute marginal-value prices and pumping update

After the user's Task 45 evidence and pricing clarification, the provisional
default pumping coefficient is **0.005 MWh_el per charging/discharging MWh**.
The preceding zero/0.003-pumping results remain historical/scenario runs. The
[annual study design](../annual_tariff_study.md) records the source, storage-wide
interpretation and why this is not a fitted discharge-only coefficient.

The updated suite passed **26 tests**, including licensed Gurobi integration.
New coverage checks absolute heat/inventory price construction, discharge
efficiency scaling, Danish-month mean controls, actual dynamic direct-price
billing and fixed local decisions in corrective dispatch. Ruff and whitespace
checks passed. Gurobi completed all three 168-hour windows in
`results/marginal_price_pilot_pump005`, covering a constant-credit control plus
four absolute/marginal direct/discharge pricing variants. Each retains the
reference, central, local and corrective results. Price/operation figures with
announced marginal signals and source tables are generated separately.

`results/annual_2024_reference_audit/audit.json` records the full-year source audit:
8,784 UTC-calendar hours, 9.6293 SOC-proxy equivalent discharge cycles, one missing
Danish-year edge hour, 370 charge-proxy hours above 23 MW and four discharge-proxy
hours above 30 MW. This is not a metered annual operational or financial baseline.
The reported roughly eight cycles still needs its source/definition reconciled;
no new annual optimisation or annual tariff/welfare result is claimed.
