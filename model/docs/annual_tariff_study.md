# Annual 2024 reference and marginal-value heat pricing

## Research question and comparison

Estimate whether a tariff reflecting heat-system marginal values induces feasible
HTF/PTES operation with lower annual operating expenditure and acceptable stakeholder
outcomes. Cycle count is an outcome and mechanism indicator, not the objective.
Neither eight historical cycles nor 26 design cycles is a target imposed on dispatch.

Keep these cases distinct:

| Case | Purpose |
|---|---|
| Reported 2024 operation | Historical context; a fixed-trajectory upstream counterfactual requires independent flows and compatible inventory/demand boundaries |
| Optimised existing monthly tariff | Matched endogenous reference under the same demand, prices, physical limits and inventories |
| Coordinated system optimum | Operational benchmark for the available joint benefit |
| Discharge priced from marginal heat value | Test the user's proposed heat-value price basis with direct heat still monthly |
| Discharge priced from stored-energy opportunity value | Include the intertemporal cost of withdrawing stored energy |
| Direct heat and discharge priced from their respective marginal values | Test both price boundaries; local HP incentives also change |
| Direct marginal price with monthly mean preserved | Separate arithmetic price-level changes from timing; does not guarantee revenue neutrality |

The historical-to-optimised difference combines observed restrictions, operating
choices, forecasting and model error. The optimised-monthly-to-dynamic difference
is the controlled tariff experiment. Do not attribute their entire difference to
tariffs or assume all extra cycles create value.

## Pumping evidence and provisional parameter

Verified 8 November 2026: [IEA Energy Storage Task 45 Q&A bank](https://iea-es.org/task-45/qa-bank/),
economic/financial aspects, PTES operational costs. It gives approximate annual
OPEX of EUR 160,000, with pumping around 80%, assuming 26 operating cycles/year.
This is a storage-wide estimate, not metered 2024 discharge-pump consumption.

If 26 means equivalent full cycles, discharged energy is `26*3300 = 85,800 MWh`.
Using **assumed** conversion `7.46038 DKK/EUR`, the implied storage-wide pumping
expenditure is `160000*0.8*7.46038/85800 = 11.1297 DKK/MWh discharged`.
The estimate does not identify a physical electricity coefficient without energy
consumption, electricity prices and the charge/discharge pumping allocation.

The user-selected default is now `0.005 MWh_el/MWh_heat`. In the existing network
this applies **per charging flow and per discharging flow**. Thus a lossless full
cycle consumes approximately `0.01 MWh_el` per delivered MWh discharged. Electricity
uses actual hourly DK2 prices and the configured, still provisional, adder.
HTF is assigned discharge pumping and upstream is assigned charging pumping under
the provisional discharge-service boundary. This is an explicit assumption;
Task 45 does not establish the contractual split.

A simple `5 DKK/MWh` **per flow** would amount to about `10 DKK/MWh discharged`
over a lossless full cycle, before other costs. It is not the same as charging
HTF the entire approximately 11 DKK storage-wide average. The implemented main
case retains hourly electricity rather than this constant approximation.
Test the coefficient and allocation; do not claim 0.005 is fitted from Task 45.
Do not add the whole EUR 160,000 annual budget on top of simulated pumping, which
would double-count its dominant component. Common fixed maintenance cancels in
matched operating comparisons; incremental wear would need its own evidence.

## Implemented marginal-price scenarios

The central Gurobi schedule provides conditional values with accepted integer
decisions fixed. Let `m_t = mu_upstream,t/(1-network_loss)` be the delivered heat
value, `s_t` the inventory-bus value and `eta_d` discharge efficiency.

`heat_value_price` sets the absolute discharge-service price to
`pi_D,t = level + scale*m_t`.

`inventory_value_price` sets it to
`pi_D,t = level + scale*s_t/eta_d`.

Direct heat can retain the monthly reference, use `m_t`, or use
`tau_reference,t + m_t - mean_month(m)`. With direct heat at `m_t` and discharge at
`s_t/eta_d`, the local route incentive before pumping is `m_t-s_t/eta_d`, consistent
with the conditional marginal derivation. HTF pays discharge pumping separately;
it is not counted twice in the service price. Immediate heat value and stored
energy value differ; applying the identical hourly heat price to both supply
routes need not incentivise discharge when HTF also pays pumping.

`discharge_discount_dkk_mwh` remains the internal settlement identity
`tau_H,t-pi_D,t`. The new families are specified as absolute prices, not arbitrary
credits. Negative prices/premiums are not clipped silently. These are prospective
research tariffs, not actual producer contract prices, and do not automatically
ensure cost recovery, participation or global decentralisation of the MILP.
Prices are frozen from a common central solve for each comparison; they are not
an iterated price equilibrium. Conditional duals can be nonunique, and large response
changes are assessed through actual integer corrective solves.

An operationally useful marginal tariff can fail the participation constraints.
For an explicit two-part tariff, let `B` be HTF bill savings before a fixed payment,
`U` the aggregate upstream surplus change and `S=B+U` the operating saving. A fixed
payment `F` from HTF to the upstream aggregate makes both accounts non-worse-off
when `-U <= F <= B`; a negative payment is a rebate to HTF. Such an interval exists
only if `S>=0`. A declared local benefit share `a` would imply `F=B-a*S`.
This is potential benefit sharing, not a modelled/agreed actual contract. A fixed
payment independent of hourly decisions does not change dispatch incentives.
Its allocation to legal actors, forecast setting, uncertainty and cost recovery
need agreement; no such payment is automatically added to the current results.

`config/marginal_price_pilot.yaml` compares these families on three 168-hour windows
with the 0.005 pumping assumption. Gurobi, eight threads, 30 MW delivered discharge
and 30 MW charging are the current operational settings. The previous pilot below
used 23 MW charging and must be rerun for the corrected symmetric limits. Run from `model/`:

```sh
cph-dispatch study --solver gurobi --study-spec config/marginal_price_pilot.yaml \
  --local-profiles data/processed/profiles_2024/local_profiles.csv \
  --figures --output results/runs/marginal_price_pilot
```

This pilot was executed with Gurobi on all three declared weeks. It is not an
annual result. In winter, pricing both routes at their respective conditional
values saves about 5,932.65 DKK operating expenditure but raises HTF expenditure
by 56,000.14 DKK. In the shoulder/summer weeks it lowers system expenditure and
HTF payments but reduces the upstream aggregate's surplus. Raw marginal pricing
therefore does not by itself establish a tariff acceptable to both sides. Actual
outcomes and solver gaps are retained in `results/archive/2026-11-08/marginal_price_pilot_pump005/study.csv`.
The previous pilot's 0.003 coefficient is a separate sensitivity, not the new default.

The existing `report` command works on each scenario subfolder, plotting actual
direct/discharge prices, PTES operation, conditional values where available,
stakeholder accounts and producer dispatch with source tables.

## Annual baseline still requiring reconciliation

The current `Data/ptes_operation_data_hourly.csv` covers all 8,784 **UTC calendar-year**
hours. It contains 32,306.78 MWh of positive inventory differences and 31,776.69 MWh
of negative differences, or **9.6293 proxy discharge equivalent full cycles** at
3,300 MWh. These are not independent metered charge/discharge quantities. The
reported roughly eight cycles may refer to another cycle definition, data treatment
or source; establish that rather than scaling the file to eight.

Its largest proxies exceed the current power limits, and inventory declines include
thermal losses. Forcing them into the current store would confound measured
withdrawals with losses and can violate minimum flow, ramp, inventory or local
demand constraints. Do not inflate demand, silently adjust power limits, or call
such a replay measured operation. Use independently recorded flows, a clearly
labelled and audited reconstruction, or aggregate historical context depending
on the available evidence. The model currently uses a remapped 2019 HTF demand
template, not measured 2024 demand.

The public input year is the **Danish** calendar year, one UTC hour earlier at both
ends than this file. Resolve that boundary and the meaning of recorded inventory
timestamps before a full-year fixed-trajectory comparison. A complete annual solve
or rolling implementation must preserve all inventories, HP up/down history, PTES
ramps and reversal lockout across horizons. Summed independent weekly solves and
an annual LP relaxation are not an annual physically integer schedule. No new
annual benefit is claimed until that workflow and baseline are accepted.

## Benefits, sensitivity and figures

Report annual operating-expenditure differences, HTF payments and real local costs,
upstream aggregate cash/cost changes and the reconciled transfer identity separately.
System cost already includes local pumping/HP/startup costs. Adding HTF bill savings
to system savings double-counts transfers. Supplier revenue is not individual
producer or VEKS profit. Full societal welfare additionally needs a justified
treatment of taxes/adders, emissions, electricity-market effects and other external
costs; initially report operating benefits and qualify any welfare interpretation.

Sensitivities should cover pumping magnitude/allocation, tariff level/timing and
cost recovery, losses and inventory endpoints, HP restrictions, demand, fuel and
electricity prices, producer availability, discharge limits and forecast horizon.
Use the same physical/input assumptions for each tariff comparison and retain the
zero-benefit or harmful cases. Counterfactual bounds, forecast uncertainty and
alternative local optima are separate from the reported solver gap.

Paper figures should show annual inventory and cumulative throughput; weekly
heat/inventory/price detail; hour-by-week charge/discharge and price maps; marginal
heat and inventory value duration curves; tariff-level/timing controls; stakeholder
cost/transfer decomposition; and sensitivity plots with solver uncertainty. Label
historical proxies, measured data, model assumptions and forecasts separately.
Generate every figure from identified accepted annual outputs, not by extrapolating
the three-week pilot or presenting proxy throughput as metered utilisation.
