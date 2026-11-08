# Findings from the corrected 30/30 MW tariff experiments

The [versioned evidence snapshot](../reports/selected_weeks_30mw/README.md) contains
the tables and figures shared with this branch. Full local runs are indexed in
[results/README.md](../results/README.md); earlier pilots are archived.

These are three selected 168-hour model experiments in 2024, not annual results
or measured tariff impacts. They replace earlier 23 MW charging examples for the
specific comparison below. Gurobi is used throughout, with 30 MW delivered charging
and discharge, pumping at 0.005 MWh electricity per charged/discharged MWh, remapped
2019 HTF demand, weather-derived COPs, common physical assumptions and fixed
1,500 MWh initial/final PTES inventories. Prices/forecasts are known in advance.

## What the evidence supports

A modest, time-varying discharge-price reduction can increase storage use and
produce positive HTF and aggregate upstream operating benefits under the model.
One of the two tested hourly sensitivities, gain 0.25, does so in all three weeks.
This is an existence result within a declared candidate family, not an optimal
tariff estimate, an out-of-sample finding or proof that every hourly tariff works.

Direct heat retains the same monthly reference tariff in every case. The hourly
discharge credit uses the conditional delivered-heat-minus-inventory value signal:

`delta_t = clip(a_month + gain*(mu_upstream,t/r - v_inventory,t/eta_d), 0, 10)`.

The intercept is selected so the arithmetic average credit is exactly 5 DKK/MWh
on each sampled Danish month. Discharge price is `tau_month - delta_t`.
The same period is also solved with constant credits of 5, 10 and 50 DKK/MWh.
Gains 0.25 and 1 were both declared before solving and all cases are retained.
Bounds prevent a supposed small discount becoming a large subsidy or a premium;
the mean is matched **after** clipping. There is no extra fixed transfer or
benefit-sharing payment in these results.

The three-week monthly reference prices average 386.856, 279.468 and 152.712 DKK/MWh.
The hourly candidate lowers these averages by 5 DKK/MWh, approximately 1.3%, 1.8%
and 3.3%. Its actual credits range 2.73–7.24 in winter, 0–10 in shoulder and 0–8.57
in summer. Arithmetic mean matching is not revenue neutrality: credits are only
paid on actual discharge, and discharge-weighted credits differ across tariffs.

## Main numerical result: hourly gain 0.25

Benefits below are against the endogenous existing-monthly-tariff reference,
which selects zero discharge in these particular weeks under positive pumping.
That reference is not the reported historical 2024 operation.

| Week, 2024 UTC | PTES discharge MWh | HTF bill saving DKK | Aggregate upstream gain DKK | Joint operating saving DKK | Combined corrective gap DKK |
|---|---:|---:|---:|---:|---:|
| 8–14 January | 1,390.34 | 3,023.68 | 3,466.02 | 6,489.70 | 524.11 |
| 15–21 April | 1,865.20 | 12,327.38 | 83,079.82 | 95,407.20 | <0.01 |
| 15–21 July | 577.73 | 2,815.26 | 10,823.75 | 13,639.02 | 26.38 |

The two gains sum to the joint saving: they must not be added to it again.
Both-account gains exceed the reported corrective-cost gap in these examples;
those gaps do not bound forecast, input, alternative-response or contract uncertainty.

The upstream account is a hypothetical consolidation of heat revenue and operating
costs. It is not identified VEKS or individual producer profit. Electricity adders
are included, so joint operating savings are not automatically full societal welfare.

## Does timing add value beyond simply lowering the price?

Compare the hourly candidate above with a **constant 5 DKK/MWh credit**, holding
the arithmetic mean reduction and all physical inputs fixed:

| Week | Constant-credit discharge MWh | Hourly-credit discharge MWh | Discharge increase | Additional joint saving DKK |
|---|---:|---:|---:|---:|
| Winter | 1,070.62 | 1,390.34 | 29.86% | 5,131.47 |
| Shoulder | 1,802.39 | 1,865.20 | 3.48% | 7,915.61 |
| Summer | 574.45 | 577.73 | 0.57% | 2,933.63 |

HTF and the upstream aggregate also each improve relative to the constant-5 case
in this base experiment. Their incremental gains are respectively 1,591.63/3,539.84
DKK in winter, 7,602.21/313.40 in shoulder and 1,201.27/1,732.36 in summer.
This controls the arithmetic price level, not the endogenous volume-weighted
payment. The conclusion concerns a transparent tariff candidate rather than a
fully isolated revenue-neutral treatment.

## Why can upstream benefit while receiving less heat revenue?

In the winter hourly example, heat revenue falls by about 9,006.79 DKK, but upstream
operating expenditure falls by 12,472.81 DKK. The difference is the 3,466.02 DKK
upstream gain. HTF retains a 3,023.68 DKK net benefit after its incremental local
costs, including discharge pumping. Price reductions transfer part of the benefit;
the underlying operating saving must fund them.

All dispatches retain common inventory endpoints. Production and cost changes are
independently reconciled from the exported hourly data, with production residuals
below 1e-5 MWh and cost residuals below 1e-4 DKK for every candidate in both the
base and lossless runs. Local heat, inventory and electricity costs are accounted
for; no free depletion or double counting of tariff transfers is used.

## Losses, timing and counterexamples

Winter's benefit is mostly reduced PTES standing loss, not a change of marginal
production technology: PTES losses fall by 42.97 MWh and upstream production by
43.89 MWh. Additional pumping reduces the net saving. In a separate zero-PTES-loss
experiment, coordinated winter charging and all response use disappear under the
announced-charging policy, and all winter benefits are zero. The fixed inventory
endpoints and horizon therefore matter to that mechanism.

Shoulder and summer operating benefits persist with zero PTES standing loss. The
gain-0.25 hourly cases save 101,012.90 and 17,109.04 DKK, with positive gains for
both accounts versus their respective monthly references. In lossless summer,
constant-5 and hourly cases discharge essentially the same 635.20 MWh, but hourly
pricing saves about 3,004 DKK more. Thus **more throughput is not the sole cause**:
timing and the upstream heat/electricity dispatch also matter. The spring base case
even produces slightly more heat overall while reducing net operating cost.

Not every candidate is mutually beneficial. With hourly gain 1, winter joint saving
is 6,920.35 DKK but the upstream point estimate is -515.61 DKK, comparable to the
524.11 DKK conservative cost-gap bound. It does not establish a positive upstream
benefit. A constant 50-credit case clearly lowers upstream surplus in winter and
summer (approximately -58,335.77 and -15,583.97 DKK). In lossless shoulder, the
hourly tariff still benefits both versus monthly pricing but redistributes some
benefit from upstream to HTF relative to constant-5. No universal dominance claim
is supported.

## What can be presented

A defensible preliminary statement is:

> In three selected-week simulations, a bounded discharge tariff informed by
> conditional system values, with a 5 DKK/MWh average price reduction, increased
> PTES use and improved both HTF expenditure and aggregate upstream operating
> surplus. Against a constant reduction with the same arithmetic mean, hourly
> timing produced additional operating savings. The mechanism and distribution
> were seasonal and sensitive to tariff strength and loss assumptions.

This can support model/mechanism results and a transparent tariff-design example.
It cannot yet establish annual welfare, actual historical behavioural response,
an increase from eight to 26 annual cycles, an optimal contractual rate, individual
supplier profit or robustness to all uncertain inputs. The annual historical file
still supplies SOC-difference proxies rather than independent flow measurements.
Actual demand, pumping allocation, contracts, forecasting, horizon/endpoints,
fuel/electricity conditions and incremental wear remain important evidence or
sensitivity needs. Do not multiply selected-week savings or cycles by 52.

## Reproduction and output locations

From `model/`, the base experiment is:

```sh
cph-dispatch study --solver gurobi --study-spec config/tariff_findings_30mw.yaml \
  --local-profiles data/processed/profiles_2024/local_profiles.csv \
  --figures --output results/findings_30_30_pump005
```

Use a new output directory when rerunning. The lossless variant changes only
`ptes.loss_per_hour` to zero and rebuilds the central schedule and all references;
its full specification is saved in the resulting `study.json`.

| Output under `model/results/` | Contents |
|---|---|
| `findings_30_30_pump005/` | Base study, all five candidate tariffs and all networks/input snapshots |
| `findings_30_30_pump005_lossless/` | Matched zero-PTES-loss sensitivity |
| `findings_30_30_paper/base/tariff_findings.pdf` | Base utilisation, stakeholder and joint-cost figure, also PNG/SVG |
| `findings_30_30_paper/lossless/tariff_findings.pdf` | Corresponding lossless figure |
| `findings_30_30_paper/evidence.json` | Source hashes, hourly price ranges and independent physical/cost reconciliation |

Both tested hourly strengths appear in the figures. Error bars show conservative
combined corrective solver gaps, not statistical confidence intervals. Reference
versus itself has a zero error bar because the same incumbent uncertainty cancels;
the source table records the displayed gap separately. Generated results are
ignored by git and should be archived with their provenance for publication.
