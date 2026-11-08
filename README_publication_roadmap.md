# PTES tariff study: publication roadmap

This checklist tracks the work needed to turn the Høje Taastrup PTES tariff study into a consistent, reproducible journal paper.

**Scope:** evaluate economically optimal operation under alternative heat tariffs and the associated operational and financial effects. The present paper does not require a behavioural model predicting HTF's actual response, deviation penalties, or a full upstream dispatch model.

The main contribution to test is whether hourly tariff variation provides additional value after controlling for the overall price level and accounting for credible PTES operating restrictions. Improved utilisation alone is not evidence of improved economic performance.

## Progress

| Stage | Main output | Status |
|---|---|---|
| 1. Define the research and payment boundary | Agreed decision rights, settlement assumptions and research question | To do |
| 2. Consolidate and correct the model | One consistent model with documented inputs and checks | To do |
| 3. Run the controlled comparisons | Verified results, economic evaluation and sensitivity analysis | To do |
| 4. Write and review the paper | Complete manuscript supported by reproducible results | To do |

Complete Stages 1–3 in order. Background and case-description writing can progress alongside the modelling; final results, abstract and conclusions follow the corrected runs. Update checkboxes as work is completed and link decisions to the relevant commit or document.

## Stage 1 — Define what the paper investigates

**Goal:** align the institutional description, modelled decisions and payment flows.

- [ ] State the research question and intended contribution relative to existing district-heating pricing and PTES studies.
- [ ] Identify who schedules and controls charging, discharging, heat-exchanger supply and local heat production.
- [ ] Confirm which stakeholder pays for direct heat, storage charging, storage discharge and pumping electricity.
- [ ] Distinguish ownership, capacity rights, scheduling responsibility and physical operation.
- [ ] Define whose objective the model minimises and which decisions that stakeholder can take.
- [ ] Distinguish upstream production costs, contractual heat-purchase prices, HTF tariffs and the value of stored heat.
- [ ] Decide whether the model represents existing arrangements or an explicitly hypothetical alternative coordination arrangement.
- [ ] Separate confirmed facts, modelling assumptions and points requiring clarification from HTF/VEKS.

**Output:** a short modelling-boundary note, a payment-flow table and an agreed research question.

**Complete when:** every decision variable and payment term has an explicit interpretation, and the case description and objective describe the same arrangement. Unresolved assumptions are clearly bounded rather than presented as established facts.

## Stage 2 — Consolidate and correct the existing model

**Goal:** make every comparison use the same physical system and a traceable set of inputs.

### Inputs and parameterisation

- [ ] Use documented measured heat flows/energy for observed charging, discharging, operating hours and cycles. Keep temperature-derived SOC changes separate.
- [ ] Reconcile the observed storage energy balance, including losses, inventory changes, data gaps and units.
- [ ] Confirm demand provenance. Use aligned 2024 demand if available; otherwise disclose the remapped 2019 profile and retain a stylised-case interpretation.
- [ ] Apply consistent timestamps, time zones, leap-day treatment and missing-data rules across inputs.
- [ ] Reconcile current COP profiles, model assumptions and saved results.
- [ ] Define whether heat-pump capacities constrain electrical input or thermal output, and implement the intended limits consistently.
- [ ] Calibrate a defensible storage-loss assumption and document the sensitivity range.
- [ ] Set comparable initial and terminal storage conditions for the optimised cases.
- [ ] Document PTES power limits, minimum powers, ramping and switching assumptions; distinguish design capability from observed network limitations.
- [ ] Include pumping expenditure consistently with the payment boundary established in Stage 1.

### Implementation and verification

- [ ] Use one model builder with explicit scenario configuration rather than independently edited model scripts.
- [ ] Implement a genuinely endogenous monthly-tariff PTES case; keep prescribed empirical operation separate.
- [ ] Apply consistent heat-pump assumptions, demand and boundary conditions across controlled comparisons.
- [ ] Check energy balances, storage limits, simultaneous operation, minimum powers, ramps and switching restrictions.
- [ ] Require successful solver termination before exporting results; record solver status, tolerance and final MIP gap.
- [ ] Record scenario settings, input versions/hashes, software dependencies and the command needed to reproduce each run.
- [ ] Ensure figures and tables identify the run from which they were generated.

**Output:** a canonical model, scenario configuration, documented data preparation and automated diagnostic summaries.

**Complete when:** a fresh run reproduces its reported outputs, and differences between scenarios are limited to the assumptions intentionally being tested.

## Stage 3 — Run the comparisons and assess the contribution

**Goal:** distinguish tariff timing, price level, storage value and technical restrictions.

| Case or comparison | Purpose |
|---|---|
| Measured 2024 operation | Empirical context; not a controlled test of tariff effects |
| Optimised monthly tariff | Endogenous operational baseline |
| Monthly tariff versus monthly-mean-matched hourly tariff | Effect of the introduced hourly price variation |
| Mean-matched versus raw CHP-based hourly tariff | Influence of the different overall price level |
| Constrained versus PTES-relaxed hourly case | Effect of PTES restrictions, with identical heat-pump assumptions |
| With versus without PTES | Storage-specific value, separated from direct tariff effects on heat pumps |

- [ ] Implement the tariff scenarios under the settlement arrangement established in Stage 1.
- [ ] Preserve the specified monthly means when constructing level-matched tariffs, including any recalibration required by a price floor.
- [ ] Evaluate every dispatch using the same upstream operational-cost assumptions.
- [ ] Report local expenditure, heat payments and upstream cost estimates separately. Distinguish transfers from estimated resource-cost savings.
- [ ] Assess supplier revenue separately: matching arithmetic mean prices does not guarantee equal revenue after dispatch changes.
- [ ] Report throughput, cycles, losses, initial/final SOC, heat imports, heat-pump output and electricity consumption.
- [ ] Test justified variations in storage losses, feasible discharge limits and upstream heat-cost assumptions; assess demand/COP sensitivity where material.
- [ ] Treat the single-CHP signal as a stylised proxy and test whether the conclusions depend on it.
- [ ] Explain the mechanism behind the results, including any cases where dynamic pricing provides little benefit or worsens outcomes.
- [ ] Compare the findings with close literature and identify what is transferable beyond Høje Taastrup.

**Output:** reproducible comparison tables, selected figures, sensitivity results and a statement of the demonstrated contribution.

**Complete when:** the main conclusion follows from controlled comparisons, survives the relevant robustness checks, and does not depend on confusing tariff reductions with system savings. A positive effect is not a completion requirement; a defensible finding is.

## Stage 4 — Write and review the paper

**Goal:** build a focused argument around the verified evidence.

- [ ] Rewrite the introduction around PTES flexibility, the multi-operator incentive problem, existing literature and the specific research gap.
- [ ] Align the case description with confirmed scheduling and settlement arrangements.
- [ ] Update the methods, equations, parameter tables and framework figure to match the implemented model.
- [ ] Present the controlled tariff comparison first, followed by technical restrictions and robustness. Use heat-pump results to explain interactions.
- [ ] Discuss transferability, cost recovery, data limitations, perfect foresight and the distinction between optimal dispatch and actual behaviour.
- [ ] Remove unsupported causal claims linking historical underutilisation solely to tariffs.
- [ ] Replace development notes with a results-based discussion and conclusion.
- [ ] Complete the abstract with verified quantitative findings.
- [ ] Generate all reported numbers and figures from the final scenario outputs; check terminology and units throughout.
- [ ] Resolve bibliography duplicates, missing definitions and references; compile and visually inspect the complete manuscript.
- [ ] Add reproducibility instructions and appropriate data/code availability statements.
- [ ] Conduct a referee-style review of novelty, methods, evidence, interpretation and journal fit.

**Output:** a complete manuscript and reproducible supporting analysis.

**Complete when:** every main claim is supported by an identified result, limitations are explicit, and no unresolved issue undermines the main comparison. Select the journal after reviewing the corrected findings: Applied Energy remains an aspirational target, with Energy a credible alternative for a strong applied case study.

## Work deferred from this paper

Behavioural preference estimation, schedule-adherence prediction, deviation penalties, full feedback to upstream dispatch and detailed thermal-state modelling remain possible extensions. Add them only if the corrected analysis identifies a specific question that cannot be answered within the present scope.

## Decision log

| Date | Decision or clarification | Evidence / commit | Consequence for model or manuscript |
|---|---|---|---|
| — | — | — | — |
