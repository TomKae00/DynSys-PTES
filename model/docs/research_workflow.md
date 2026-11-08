# HTF/PTES model audit and research workflow

This is the migration audit, including earlier diagnostic results. For the current
30/30 MW evidence, start with the [versioned results](../reports/selected_weeks_30mw/README.md)
and [findings](findings_30mw.md). Superseded local runs are now in
`results/archive/2026-11-08/`; embedded original solve metadata is preserved.

Review date: 8 November 2026. Development branch: `feature/ptes-tariff-derivation`.
The root scripts, staged publication roadmap, IDE settings and existing generated
inputs/results have been preserved. The Gurobi/eight-thread settings already in
`config/base.yaml` are the user's changes. Gurobi is the research solver. It requires
execution outside the sandbox here to access its host-bound licence; the normal
sandbox reports a host-ID mismatch. Portable HiGHS tests remain available.

The requested operational case now has **30 MW delivered PTES discharge**, with
30 MW delivered charging. `discharge_power_mw` explicitly overrides the symmetric
fallback. Ramps/minimum flows/reversal constraints are unchanged. Earlier benchmarks
below used the old symmetric 23 MW case and are labelled separately. The
[validation update](history/validation_before_cleanup_2026-11-08.md#htf-tariff-workflow-and-30-mw-discharge--8-november-2026)
records the completed 30 MW Gurobi runs and the three-season pilot outcomes.

## Architecture and adding components

The existing `src/cph_dispatch` package is a suitable canonical model. Keep the
physical problem in PyPSA/Linopy, fixed capacities in configuration, and upstream
dispatch as a mechanism for valuing local flexibility. Separate these responsibilities:

| Module | Responsibility |
|---|---|
| `profiles.py` | Weather → historical DH steering curves → local COPs |
| `data.py` | Public downloads, bounded repairs, template or timestamp alignment |
| `optimisation.py` | Native network components, operational constraints, solver acceptance, conditional duals |
| `results.py` | Physical extraction, hourly losses/balances and independent cost/settlement accounting |
| `workflow.py` | Shared central schedule, local response, corrective dispatch, stakeholder accounts and response ambiguity |
| `tariffs.py` | Documented candidate-credit derivation and price-level controls |
| `study.py` | Matched parameter/period sweeps and explicit finite-family selection |
| `observations.py` | Recorded-data evidence classification and contextual comparisons |
| `analysis.py` | Physical and economic explanation of case differences |
| `plotting.py` | Figures plus their source tables and provenance |
| `cli.py` | Input/output orchestration and atomic publication |

To add a physical component: (1) declare its parameters/units/evidence in config;
(2) create native components in `build()` using a helper if a technology family
warrants one; (3) add only the missing coupling/operational rules in
`add_constraints()`; (4) extend extraction and **both** cost accounts as applicable;
(5) add a physical/economic regression that would fail for the likely modelling
mistake; (6) document its metering and payment boundaries. A new tariff belongs in
`tariffs.py`, a scenario in YAML, and a figure in `plotting.py`. Do not fork another
independent model script per experiment. Existing exported networks still require
the custom builder/constraint callback to re-optimise.

## What was inherited, changed or missing

| Original logic | Audit and current treatment |
|---|---|
| `build_dh_temperature_profile.py` | Preserved 24-hour ambient average with 23 prior hours, all three 1996 steering curves, highest curve as supply proxy, optional margin/bounds and 50°C return. Tests compare a full leap year against the original functions. These historical curves are not a calibrated current HTF controller. |
| `build_cop_profile.py` | Preserved Lorenz/refrigerant approximation, pinch/efficiency parameters, groundwater 10.5→4°C, City2 12→8°C, soil sinusoid and cutoffs. Zero-COP hours now disable the HP rather than creating division by zero; full-output policy rejects that conflict. Soil COP is retained as a profile, not an invented third HP. |
| Frozen local COP input | The inherited file numerically matches the root COP file. Preparation previously treated it as a fixed-CET template, shifting its actual UTC weather chronology. Legacy mode remains available to reproduce runs. `profiles` + `--local-profiles` provides strict timestamp alignment, including the first Danish-year hour. |
| `fixed_ptes_comparison_2024.py` | Historical comparison is restored as a report operation. Its blanket fill, upward demand adjustment, constant COPs and forced replay of SOC-derived flows are not carried forward as physical validation. Demand is never inflated to accommodate a proxy. |
| PTES restrictions | Capacity, minima, initial idle ramps, exclusive modes, reversal lockout, inventory endpoints/efficiencies/losses retained. Optional `charge_power_mw` / `discharge_power_mw` override the symmetric fallback. The unclarified 12-hour rule and thermal stratification remain absent. |
| First-hour loss and CHP bypass | Retained and tested. AMV4 full heat-only ceiling is 550 MW before derating; bypass means extra capability. |
| HP policy | Thermal capacity, minimum load, up/down times and starts retained. Real seasonal availability and restrictions are still missing; full-output is a scenario. |

With the existing ERA5 files, regenerated COPs agree with the root file on common
actual UTC timestamps to less than `5e-15`. The new profiles cover the Danish year
(2023-12-31 23:00 UTC to 2024-12-31 22:00 UTC), whereas the root output covers the
UTC calendar year. Missing edge hours are errors, not extrapolated values.

The recorded file `Data/ptes_operation_data_hourly.csv` has charge/discharge exactly
equal to positive/negative hourly inventory differences (maximum discrepancy
`9.14e-13 MWh`). Those columns cannot independently measure throughput or losses.
Their maxima, approximately 37.59/33.85 MWh per hourly interval, also exceed the
old 23 MW scenario and the requested 30 MW discharge limit. The report labels them `soc_proxy`; declaring them `metered`
fails explicitly. Historical inventory can be plotted as context, with timestamp
and thermal-energy-estimation uncertainties acknowledged. No causal tariff impact
or empirical loss calibration follows from this comparison.

## Heat production cost versus the price HTF pays

[Varmelast's dispatch description](https://www.varmelast.dk/lastfordeling/hvad-er-lastfordeling)
distinguishes joint variable production expenditure net of electricity sales from
payments under individual heat-purchase agreements. The latter allocate costs
between heat and power and need not equal the dispatch cost. The present objective
represents the former principle with scenario costs. Taxes, actual bids, plant
commitment, priority waste dispatch and network bottlenecks remain incomplete.

The [August 2024 EML study, sections 4.2–4.3](https://www.varmelast.dk/-/media/varmelast/dokumenter/eml-lastfordeling-efter-kontraktpriser-v2.pdf)
uses separate cost-based and contract-price-based dispatch. It describes
cost/electricity-revenue sharing, bypass compensation and extraction-unit contracts;
its simplified confidential-contract treatment and 2030 planning assumptions do
not supply the actual 2024 HTF/VEKS agreements. Therefore the present package
does **not** claim to reproduce contractual heat-price calculation.

Available outputs are conditional marginal production/delivery values, aggregate
operating expenditure and hourly CHP joint net costs. The latter credit all CHP
electricity sales and may include condensing income; dividing them by heat is only
a labelled accounting ratio. Neither those ratios nor bus duals are contractual
rates. Keep the inherited monthly HTF tariff separate. A contractual extension
needs the actual allocation keys, variable/fixed terms, bypass rules, taxes and
stakeholder boundaries. No unverified contract coefficients have been invented.

## Candidate tariff derivation

Use the discharge-service boundary provisionally: HTF pays `tau*H + pi_D*D`, local
HP costs and discharge pumping. Upstream bears charging heat and charging pumping.
This requires contractual confirmation. Do not switch to local charging purchases
merely because the original fixed-dispatch script used that boundary.

Let `delta = tau - pi_D`, `r = 1-network_loss`, `mu` the upstream bus marginal
value and `v` the inventory-bus value. All duals come from the continuous problem
with accepted integer choices fixed (or a clearly labelled LP relaxation).
For marginal discharge replacing direct heat, the conditional system saving is

`mu/r - v/eta_discharge - kappa*(electricity_spot + local_adder)`.

HTF's isolated substitution incentive is
`delta - kappa*(electricity_spot + local_adder)`.
Matching these marginal incentives suggests the candidate

`delta_value = mu/r - v/eta_discharge`, hence `pi_D = tau - delta_value`.

This is a local marginal derivation, not proof of decentralisation of the entire
integer/intertemporal problem. Conditional duals can be nonunique, bounds can bind,
HP decisions can change, and terminal inventory influences opportunity value.
Small boundary perturbations test sign and unit scaling. Material deviations and
candidate responses are evaluated by actual PyPSA integer re-optimisation.

The implemented family is:

- `constant`: `delta = level`.
- `marginal_value`: `delta = level + scale*delta_value`.
- `monthly_mean_matched_value`: `delta = level + scale*(delta_value - monthly_mean)`.

Monthly matching uses Danish months on the evaluated snapshots. It controls the
arithmetic mean on those hours, not a full-month mean if only a week is sampled,
volume-weighted payments or supplier revenue. There is no hidden clipping: negative
credits mean a discharge premium, and a discharge price can be negative. A future
price floor/cap needs an explicit recalibration and sensitivity.

`study` includes the zero-credit reference, reuses one central/reference pair per
period/physical scenario, retains every candidate's local and corrective solution,
and selects minimum corrective operating cost **within the tested family**. It also
reports the best candidate passing an aggregate participation screen and alternatives
whose corrective-cost solver intervals overlap the best accepted cost. The screen
cannot establish participation by each legal actor. This is in-sample perfect-foresight
search, not an out-of-sample estimate or a globally optimal contract. Test levels
are illustrative; reporting their range is preferable to false price precision.

## Stakeholders, resource accounting and welfare

`results.py` independently reconciles fuel, O&M, electricity purchases/adders,
electricity sales and startup expenditure to the objective. Internal heat transfers
never enter the system objective. For candidate versus matched reference:

`HTF bill saving + aggregate upstream operating-surplus change = operating-cost saving`.

The upstream aggregate includes the local heat-revenue change and upstream cost
change, after removing local HP/discharge-pump/startup costs from system cost. It
is a hypothetical consolidated account, not VEKS, producer or Varmelast profit.
Splitting it requires real contracts and cost ownership. The default boundary
assumes that other regional payments cancel in matched comparisons.

Operating savings include scenario electricity adders, which can themselves be
transfers. They are not a complete social-welfare measure: investment, externalities,
market power and household utility are omitted. Do not add HTF bill savings to
system savings. Do not interpret spot-price corrective dispatch as electricity
balancing settlement. Deviation charges remain deferred until timing, allowable
recourse and liability have an agreed meaning.

For a proposed rate, inspect HTF bill change, upstream aggregate change and system
cost, rather than declaring success from increased cycles. A negotiated fixed
transfer might share positive joint gains, but it would need an explicit contract;
the current screen adds none automatically.

## Winter diagnosis and reference ambiguity

Existing **23 MW** Gurobi results in `results/archive/2026-11-08/tariff_comparison` reconcile as follows:

| Candidate versus zero-credit reference | Value |
|---|---:|
| HTF bill saving | 74,315.43 DKK |
| Operating-cost saving | 16,007.35 DKK |
| Hypothetical upstream surplus change | -58,308.09 DKK |
| PTES standing-loss reduction | 40.67288 MWh |
| Avoided upstream production | 41.53062 MWh |
| Production reconciliation residual | <2.3e-9 MWh |
| Cost decomposition residual | <4.4e-6 DKK |

The saving is explained by reduced PTES inventory/losses, delivery losses and a
small regional-loss change; the configured marginal gas boiler supplies the
production difference. This does not demonstrate substantial technology-switching
arbitrage or that a 50 DKK/MWh rate benefits everyone.

A fresh **23 MW** 168-hour HiGHS comparison gives 9,264.62 DKK operating savings and 75,336.67
DKK HTF savings. It chooses 599 MWh reference discharge rather than zero with the
**same HTF expenditure**. Central objectives differ by 122.36 DKK, within the
reported central gaps. This is not an empirical contradiction: zero pumping and
equal route tariffs leave HTF indifferent.

The optional `--response-range` diagnostic minimises/maximises total discharge
under the original physical rules and an HTF-expenditure ceiling equal to its
accepted optimum plus 0.01 DKK. With the reproduced winter charging ceiling,
the range is 0–1,506.73 MWh, with zero secondary solver gaps. These are extrema
within a near-optimal band, not pointwise bounds or predicted schedules. No
arbitrary preference or pumping penalty is inserted to choose an attractive
baseline. Actual pumping data, restrictions or a justified behavioural assumption
are needed before attributing a unique benefit to the tariff.

`response.local_mip_rel_gap=1e-8` tightens expenditure solves: otherwise a tolerance
on the large total heat bill can exceed the small incentive being studied. Main
central/corrective gaps remain configurable and reported. Their sum bounds the
cost difference for the accepted local trajectories, not uncertainty from other
local optima, input assumptions or forecasts.

## Scientific experiments and remaining evidence

Start with the offline smoke configuration, then selected cases from
`config/tariff_study.yaml`. It crosses winter/shoulder/summer weeks with pumping,
lossless, 30 MW/asymmetric and HP-policy sensitivities. Each sensitivity gets its
own matched coordinated and zero-credit baseline. Pumping ranges are assumptions,
not measurements. An illustrative synthetic case with positive pumping verifies
that a credit changes feasible local use and that excessive discounts can reduce
upstream surplus. This is a methodology check, not a result about actual HTF.

Next prioritise measured discharge pumping and HP operating restrictions; measured
2024 local demand and the gross-demand/metering boundary; actual loss and capacity
calibration; then alternative horizon/end-inventory scenarios, fuel/availability,
electricity-price and tariff-range robustness. The current sweep has fixed inventory
endpoints. Longer-horizon/rolling experiments must carry inventory and commitment
histories; there is no new rolling or annual integer result here. The full supplied
multi-period sensitivity design has not been run as part of this review.

Figures are generated from accepted exports in PDF/SVG/300-dpi PNG, with source
CSV tables, diagnostic JSON, hashes and a manifest. Local balance, PTES net flow,
inventory/context, tariffs/conditional values, producer heat and **net** regional
storage are separate. Transfers and operating savings have separate panels;
error bars show corrective-solver uncertainty only. Captions must state template
demand, modelled COPs, perfect foresight, provisional pumping/losses and the exact
run. A historical comparison is contextual, not a controlled tariff experiment.
