# PyPSA validation record — 5 November 2026

These checks validate the implementation and numerical feasibility. They do not
establish empirical calibration, actual operator behaviour or an optimal tariff.
[validation_inputs.json](validation_inputs.json) records source hashes and each data
repair; [validation_metrics.json](validation_metrics.json) records the executed cases.

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
