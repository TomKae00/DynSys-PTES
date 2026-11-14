# Storyline, positioning and workshop plan

Companion to `applied_energy_plan.md`. That file lists the workstreams (A–F) and risks;
this one fixes the story the paper tells, how it relates to earlier work, which results
each claim needs, and what the workshop on 3 December has to deliver for it.

Status: 14 November 2026, second version (Frigg mechanics and the pricing literature
checked against open-access full texts). Sources marked [n] are listed at the end.

---

## 1. The story in six steps

1. **PTES has a clear system value.** Energy-system studies find lower system costs with
   PTES in district heating [1–3]. Our own PyPSA-DE study finds 135–345 M EUR per year for
   Germany even when temperature limits are represented [1]. All of these studies assume
   one planner who operates the store optimally.
2. **The first large PTES in a metropolitan, multi-company system is used far less than
   planned.** Høje Taastrup: about nine equivalent cycles in 2024 against a design range
   of 25–30 [4]. Several causes are technical. One is not: the store is scheduled by
   Varmelast, discharged by HTF, and settled at a flat monthly tariff that is the same for
   heat through the heat exchanger and heat from the store, while HTF pays the pumping.
3. **The value of flexibility therefore does not reach the party that has to act.** In
   Greater Copenhagen the dispatch fixes quantities, but the prices it implies are not
   used; heat is paid at prices fixed in contracts [19]. Who benefits from a PTES was
   already unclear to the actors at the investment stage [5].
4. **Dynamic heat prices are the known remedy for flat prices, but they were developed for
   other responders.** End consumers and buildings [6–9, 23], or third-party and
   excess-heat producers [10, 19]. The signal there is the marginal cost of heat. For a
   store, the signal that matters is a difference: the value of delivering heat now minus
   the value of keeping it stored.
5. **Method: price-based coordination instead of assumed compliance.** As in Frigg
   [6, 7], the response is not dictated. A central schedule gives prices, a separate
   model of HTF responds, and the upstream system is re-dispatched around that response.
   Unlike Frigg, the price is derived from the dual values of the coordinated schedule
   and not optimised as a variable (section 2.1).
6. **Result and message.** A small, time-varying discharge credit recovers about 80 % of
   the coordination value, both sides gain, and the size of the transfer is a design
   choice. Timing matters more than level. A discharge tariff cannot correct the local
   heat-pump incentive. Copenhagen is the first system where this can be tested against
   measured operation; the conditions that make it relevant will appear elsewhere as
   stores are built at company boundaries.

One-sentence version: *system models promise a PTES value that a flat settlement at a
company boundary does not deliver; a credit derived from the planner's own heat values
closes most of the gap and leaves both sides better off.*

---

## 2. Positioning against earlier work

| Strand | What it established | What we take | What is different here |
|---|---|---|---|
| Flexibility Function and Frigg (DynSys) [6, 7, 18] | Flexibility should be modelled as a response to prices (indirect control), soft-linked to a dispatch model, not as central control | Indirect control; the sequence optimise, respond, re-dispatch; a bounded price signal; single pass | Price from duals instead of an optimised signal; responder is a cost-minimising company, not a response function; payments and each party's account are explicit (section 2.1) |
| Dominković et al., dynamic pricing in district heating [10] | Hourly heat price from the marginal cost of supply, set like a day-ahead market; effect of waste heat and storage on that price | Marginal value of heat as the basis of a price | With a store the hours are linked; we use the duals of the heat balance and of the store, and price their difference (section 2.2) |
| Heat market design for Copenhagen (DTU) [19, 20] | Varmelast dispatch as a marginal-cost market whose prices are not used; price-signal self-scheduling vs market participation for excess heat; sequential heat and electricity clearing | Motivation; the dual of the heat balance as the heat price; sequential markets for C7 | Their responders are producers; none prices storage use across a company boundary |
| Design of dynamic heat prices [8, 9, 23] | Day-ahead price profiles from flexibility characterisation and inverse optimisation; leader–follower heat pricing; marginal cost alone is not a good demand-response signal [8] | Announce-then-respond framing; the point that a raw marginal value needs shaping before it is a tariff | Their follower is the consumer side |
| Wholesale and marginal-cost heat pricing more broadly [21, 22] | Shadow-price and merit-order pricing as alternatives to cost-plus tariffs | Terminology and background | Heat price, not storage |
| PTES in energy-system models [1–3] | System value; importance of temperatures; PTES cycles weekly to monthly rather than seasonally | Motivation and scale | They assume ideal operation; we ask whether the value is realised under real settlement |
| PTES operation at Høje Taastrup [4, 12] | Measured performance, about nine cycles in 2024, short-term design | Reference case and data | Adds the economic explanation and a remedy |
| Storage remuneration and TSO–DSO coordination in electricity (transferability table from 10 Nov) | Flexibility owned at one level and needed at another needs its own remuneration | The analogy | First application to heat storage between a transmission and a distribution company |

### 2.1 Frigg: what we follow and where we depart

How Frigg works, from the thesis and the Frigg 2.0 paper [7, 18]:

- The price signal is a **decision variable** of the central problem, bounded between −1
  and 1. The central problem contains a model of the response (the Flexibility Function)
  and chooses the signal that leads to the cheapest dispatch. It is not a dual value.
- Frigg 1 solves this by backward dynamic programming over the discretised flexibility
  state. Frigg 2.0 replaces this by a MILP with a piecewise-linear Flexibility Function,
  because dynamic programming did not scale to storage and investment.
- The average absolute price signal is capped (Δ). Without a cap the indirect problem
  collapses into direct control.
- Frigg 2.0 runs **once**, with no iteration: (1) baseline dispatch, (2) optimisation with
  the approximated response, (3) simulation of the actual response to the resulting
  price signal, (4) dispatch re-solved with that response fixed, (5) European dispatch
  rerun.

Mapping to our framework:

| Frigg 2.0 | This paper |
|---|---|
| Central optimisation gives the price signal | Coordinated schedule gives the heat and storage values, from which the credit is computed |
| Simulation of the actual response to the signal | HTF minimises its own expenditure under the tariff |
| Dispatch re-solved with the response fixed | Corrective dispatch |
| Cap Δ on the signal | Credit bounded to 0–10 DKK/MWh with a fixed monthly mean |
| Single pass | Single pass |

Differences to state in the paper:

1. **Dual-derived instead of optimised.** Our coordinated schedule does not contain a
   model of HTF's response, so the credit is not the best possible one. The gap between
   the hourly credit and full implementation of the schedule (about 19 % of the
   coordination value) bounds what an optimised credit could add. The sweep (B1) searches
   the design space; optimising the credit directly is a possible extension.
2. **Responder.** Frigg uses an estimated response function with a normalised signal. We
   model a company with a store, pumps and heat pumps that minimises its expenditure.
3. **Money.** Frigg limits welfare loss through Δ. We have actual payments, so we report
   the system cost and each party's account separately.

Consequence for the plan: the one-pass coupling has a direct precedent in Frigg 2.0. The
iteration test (C4) stays as a robustness check but is not needed to justify the design.
The more likely reviewer question becomes "why not optimise the credit as Frigg does?",
which difference 1 answers.

### 2.2 Dominik's work and the dual-based price

- **Closest paper: [10].** The hourly heat price is the intersection of the marginal-cost
  supply curve and demand, set up like the day-ahead electricity market, for Sønderborg
  and Espoo, including scenarios with waste heat and thermal storage. Without links
  between hours this price equals the dual of the hourly heat balance. The paper does
  not, as far as the accessible text shows, formulate it as a dual.
- **Our step beyond it.** With a store, hours are linked. The dual of the heat balance
  then contains the storage value, and the store has its own dual. The credit is the
  difference between the two. That is the methodological addition to state.
- **Other work by him that fits the context:** soft-linking of a planning and an
  operational model with a flexibility characterisation and feedback, Zagreb [11];
  thermal building mass as storage in district heating; an optimisation model of a
  trigeneration plant with PTES; district heating expansion with storage sizing [25].
  He is senior author on both Frigg papers. His marginal-cost method was reused to price
  data-centre waste heat [24], which is relevant for HTF's data-centre heat pumps.
- **Not found:** a published paper of his that derives dynamic prices explicitly from
  dual variables, and nothing under the name "Dominik Doko". If this refers to internal
  DynSys work, the document is needed.
- **Explicit dual-based heat prices elsewhere:** Frölke, Palm and Kazempour [19] define
  the uniform heat price as the dual of the heat balance in a Copenhagen market model.
  This is the cleanest citation for "price from the dual".

### Research gap (draft wording)

Studies of dynamic heat pricing address the price faced by end consumers or by
third-party and excess-heat producers, and use the marginal cost of heat as the signal.
System studies of PTES assume that the store is operated by a single planner. How to
settle the use of a store that is planned by one company and operated by another has not
been addressed: the relevant signal is the difference between the value of delivering
heat now and keeping it stored, and it has to hold against the operator's own costs and
local assets.

The "has not been addressed" claim rests on targeted searches only. It needs the
systematic search in E1 before it goes into the paper.

---

## 3. Generalisation: Copenhagen as a first case

Argue in three layers, from firm to forward-looking.

1. **Conditions, not places.** The result transfers where (a) one party schedules and
   another implements, (b) the settlement price is flat while the value of heat varies,
   (c) the implementer bears an operating cost, (d) the store is small relative to the
   system. This is section 7.4 of the plan and stays the core of the argument.
2. **Systems that already have the company structure.** Transmission companies that sell
   to separate distribution companies exist beyond Copenhagen, for example the regional
   heat links in Germany (Rhein-Neckar with Mannheim, Heidelberg, Schwetzingen and
   Speyer; Niederrhein) [13, 14]. These do not have a PTES at the boundary today. They are
   candidates, not cases.
3. **The store pipeline.** German PTES so far are small and belong to one utility
   (Meldorf, Bracht, Hechingen) [15]; larger and urban projects are in preparation, for
   example in Vienna and in the EU TREASURE demonstrators [16, 17]. As stores grow and are
   placed where land is available, more of them will sit in a distribution area while
   serving the whole system.

A fourth argument comes from [19]: simple price signals work while the responding
capacity is small and become inefficient as it grows. The same should hold for stores,
which supports deriving the credit from the plan instead of fixing it.

**What our PyPSA-DE paper [1] can carry.** It supports scale and relevance: PTES lowers
system costs in a net-zero Germany. It does not say anything about company boundaries.
Its main message is also a caution: models without temperature limits overstate the
benefit. Cite the 135–345 M EUR range, not the idealised 15 %.

**Consistency risk.** The same paper argues that temperatures must be modelled. The
tariff model has no temperatures. State this in the limitations and tie it to the
observed 23 MW discharge limit and the summer conditions (D4), otherwise a reviewer who
knows [1] will raise it.

---

## 4. Claims and the evidence they need

| # | Claim | Evidence | Status |
|---|---|---|---|
| 1 | Coordinated use of the store has a value that the current settlement does not realise | Measured 2024 vs coordinated schedule; coordination value 7.63 MDKK (7-day rolling), 5.18 (weekly), 3.72 (24 h) | Done |
| 2 | Following the schedule costs HTF under the current tariff | Full-implementation case | Done (weekly); confirm in rolling |
| 3 | A small time-varying credit recovers most of the value and both sides gain | Hourly credit 81–84 % across planning set-ups; weeks in which both gain | Done; parameters not yet justified |
| 4 | Timing matters more than level; the transfer is a design choice | Hourly credit vs value share; frontier of saving vs transfer | Partly; needs B1–B3 |
| 5 | Holds under realistic planning | Rolling 24 h and 7 days done; forecasts (A5) | Partly; A5 waits for Varmelast |
| 6 | Robust to uncertain inputs | C1, C2, tornado, break-even pumping cost | Configs ready, runs not started |
| 7 | A dual-derived, announce-then-respond credit is adequate | Gap to full implementation; B1 sweep; C4 and C6 as checks | Gap known; sweep not started |
| 8 | Following the schedule has a value beyond day-ahead costs | Deviation volumes; C7 with imbalance prices | First volumes only |
| 9 | A discharge tariff cannot correct local heat-pump operation | Heat-pump gap | Fragile: modelled heat pumps produce about twice the reported output; needs D2–D3 |
| 10 | The store raises what can be delivered across the boundary | Not tested. Would need hours in which the 100 MW heat exchanger binds, or a case with lower exchanger capacity or higher peak demand | Decide after the workshop |
| 11 | Transfers to other systems | Conditions, transferability table, one other price year | Table drafted; price-year run optional |

Claims 1–3 are the paper. Claims 4–8 are what makes it an Applied Energy paper. Claim 9
should be downgraded to a secondary finding until HTF's data arrive. Claim 10 is part of
the intended message but has no result behind it yet.

---

## 5. Gaps

**In the narrative**
- Relation to Frigg and to Dominik's work is asserted in one sentence of the draft, not
  explained. The introduction and the framework section need the content of 2.1 and 2.2.
  The draft should not suggest that Frigg derives prices from duals.
- The introduction starts from Høje Taastrup. Starting from the system value of PTES
  (step 1) and the realised use (step 2) makes the case study an instance of a general
  problem.
- "More heat across the boundary" and "pioneer for other systems" are in the intended
  message but not in the results (claims 10 and 11).
- Incentive vs feasibility: the paper must separate what HTF cannot do (23 MW, gradients,
  summer temperatures, network) from what does not pay. Without HTF's input this split
  is an assumption.

**In the model**
- Tariff parameters chosen, not derived (B1, B2).
- Credit not optimised; one-pass coupling untested (B1, C4, C6).
- Corrective dispatch at day-ahead prices understates the cost of deviations (C7).
- Local system: demand about 8 % low, about 18 GWh of data-centre and solar heat
  missing, heat pumps about twice too high (D1–D3).
- No temperatures; heat exchanger and peak coverage not examined (D4, D5, claim 10).
- Perfect foresight within the horizon; no forecasts (A5).

**In the data**
- HTF: hourly demand and local production, operating limits, electricity costs.
- Varmelast: planned 2024 schedules, horizon and terminal value, forecasts.
- VEKS: pass-through in the heat purchase agreements, so that "upstream gains" can be
  attributed to VEKS or to the producers.
- What may be published.

---

## 6. Workshop, 3 December

Format agreed with Ida: 1.5 h; current paper and results to participants by 23 November;
a 10-minute overview from Tom as a basis for discussion. HTF joins for the first time.

**What the story needs from each party**

| Party | Question | Settles |
|---|---|---|
| HTF | What limits discharge in practice, and which local sources run by default? | Incentive vs feasibility; claim 9; D2–D5 |
| HTF | Would a credit announced with the day-ahead plan be usable in daily operation? | Implementation section (B4) |
| HTF, VEKS | Does the heat exchanger ever limit supply to HTF, today or with expected growth? | Whether claim 10 is worth testing |
| Varmelast | How is the PTES planned (horizon, revisions, value of heat left at the end)? Could heat values from the plan be published with it? | Claims 5 and 7; whether the credit is implementable in the existing planning run |
| Varmelast | How are deviations handled today, and how will the planned imbalance market work? | Claim 8; C7 |
| VEKS | How do cost changes pass through the purchase agreements? | Who gains upstream; sharing rule |
| All | Which designs should be analysed further: hourly credit, value share, payment for following the schedule, charge for deviations? | Scope of B3 |
| All | Which data can be shared and shown, and do the partners want to review the paper? | F3, E7 |

**10-minute overview (six slides)**
1. The set-up: who plans, who operates, who pays what.
2. The question, in neutral terms: how can the settlement pass the value of storage use on?
3. The approach in one figure: schedule, credit, response, re-dispatch.
4. Main result from the 7-day rolling study: value, recovered share, split between the sides.
5. What the result depends on and what is not yet known.
6. What would help from each party.

**Package for 23 November**
- Draft rebuilt around the 7-day rolling results, weekly study as a check.
- Introduction restructured along section 1 (needs no new runs).
- Sweep and sensitivities included if finished; otherwise announced as next steps.
- Leave the deviation table (45 GWh for measured operation) out of this version or mark
  it clearly as an upper estimate against the model's plan. It compares measured
  operation with a perfect-foresight schedule and can read as criticism.

---

## 7. Sequence

The sweep and sensitivity runs had not been started on 14 November. They are the only
items on the path to 23 November that need compute time.

| When | What |
|---|---|
| 14 – 17 Nov | Start C1 and the sweep B1 in the 7-day rolling set-up (overnight, Gurobi) |
| 15 – 20 Nov | Restructure introduction; write the Frigg and pricing paragraphs from 2.1 and 2.2 |
| 20 – 23 Nov | Analyse sweep (frontier, smallest sufficient credit); update draft; send package |
| 24 Nov – 2 Dec | Slides; C4 and C6 on the weekly study; start E1 search per theme |
| 3 Dec | Workshop; decide on claim 10 |
| Dec – Jan | Data-dependent work (A5, A6, D1–D5), C7, generalisation and policy sections, full rewrite of results |

---

## 8. Open points

1. Dominik's reference: [10] is the closest published paper. Confirm with Henrik whether
   internal work on dual-based prices exists that should be cited or acknowledged.
2. Frigg: resolved, see 2.1.
3. Claim 10: decide after the workshop.
4. Runs: to be started.

---

## Sources

1. Schauß, Schledorn, Kähler, Schumacher, Ammon, Brown (2026), Mind the Temperature Gap. Preprint: https://arxiv.org/abs/2601.07647v1 (published version: https://www.sciencedirect.com/science/article/pii/S2666792426000545, not readable from here; numbers above are from the preprint abstract)
2. Sifnaios et al. (2023), The impact of large-scale thermal energy storage in the energy system, Applied Energy 349. https://orbit.dtu.dk/en/publications/the-impact-of-large-scale-thermal-energy-storage-in-the-energy-sy/
3. Burkhardt, Frömel, Deac, Billerbeck (2026), Flexibility through thermal energy storage, Energy 356. https://publikationen.bibliothek.kit.edu/1000193559
4. Sifnaios, Jensen (2025), Performance analysis of the Høje Taastrup water pit thermal energy storage (cited in the draft as sifnaios2025performance).
5. Bertelsen, Petersen, Thermal Energy Storage in Greater Copenhagen, Aalborg University. https://vbn.aau.dk/ws/files/260124158/samlet_fardig.pdf
6. Schledorn, Junker, Guericke, Madsen, Dominković (2022), Frigg: Soft-linking energy system and demand response models, Applied Energy 317. https://doi.org/10.1016/j.apenergy.2022.119074
7. Schledorn, Charousset-Brignol, Junker, Guericke, Madsen, Dominković (2024), Frigg 2.0, Applied Energy 364. Open access: https://static1.squarespace.com/static/635121e28a76f94ed988ed7b/t/66571b8036008c6fe67e8ea8/1716984709404/Frigg+2.0_Integrating+price-based+demand+response+into+large-scale+energy+system+analysis.pdf
8. Mokhtari, Junker, Madsen, Li (2025), A methodological framework for designing dynamic heat price for demand response in district heating, Energy 324. https://annex82.iea-ebc.org/Data/publications/A%20methodological%20framework%20for%20designing%20dynamic%20heat%20price%20for%20demand%20response%20in%20district%20heating.pdf
9. Bai, Pinson, Wang (2022), Variable heat pricing to steer the flexibility of heat demand response in district heating systems, Electric Power Systems Research 212. https://orbit.dtu.dk/en/publications/variable-heat-pricing-to-steer-the-flexibility-of-heat-demand-res/
10. Dominković, Wahlroos, Syri, Pedersen (2018), Influence of different technologies on dynamic pricing in district heating systems, Energy 153. https://www.sciencedirect.com/science/article/abs/pii/S0360544218306327
11. Dominković, Junker, Lindberg, Madsen (2020), Implementing flexibility into energy planning models, Applied Energy 260. https://ideas.repec.org/a/eee/appene/v260y2020ics0306261919319798.html
12. PTES in Høje Taastrup, project description. https://www.districtenergyaward.org/wp-content/uploads/2023/11/PTES-in-Hoje-Taastrup.pdf
13. ZfK, Die größten Fernwärmenetze in Deutschland. https://www.zfk.de/energie/die-groessten-fernwaerme-netze-in-deutschland
14. BDEW, Wärmewende in der Fernwärmeversorgung. https://www.bdew.de/verband/magazin-2050/waermewende-der-fernwaermeversorgung-vier-praxisbeispiele-aus-vier-staedten/
15. Ramboll, presentation on PTES in Germany (Meldorf, Bracht, Hechingen). https://www.hlnug.de/fileadmin/dokumente/geologie/erdwaerme/fachgespraech/2023/04_Maretzki.pdf
16. Wien Energie, Projekt ScaleUp. https://www.wko.at/oe/oegew/projekt-scaleu.pdf
17. TREASURE project. https://cordis.europa.eu/project/id/101136095/reporting
18. Schledorn, PhD thesis, Modelling of flexibility-centric energy systems, DTU. https://backend.orbit.dtu.dk/ws/files/360704766/PhD_Thesis.pdf
19. Frölke, Palm, Kazempour (2022), Market Integration of Excess Heat, PSCC 2022. https://arxiv.org/abs/2204.12953
20. Mitridati, Kazempour, Van Hentenryck, Electricity-Aware Bid Format for Coordinated Heat and Electricity Market Clearing. https://arxiv.org/abs/2005.03120
21. The marginal-cost pricing for a competitive wholesale district heating market: A case study in the Netherlands (2019; authors and journal to verify). https://www.researchgate.net/publication/336656268
22. Li, Sun, Zhang, Wallin (2015), A review of the pricing mechanisms for district heating systems, Renewable and Sustainable Energy Reviews 42.
23. Optimal price signal generation for demand-side energy management, Smart Energy 17 (2025) 100173 (DynSys; author list to verify). https://static1.squarespace.com/static/635121e28a76f94ed988ed7b/t/67f8dd3ad051313046fc8db6/1744362820654/Optimal+price+signal+generation+for+demand-side+energy+management.pdf
24. Wahlroos et al. (2018), Waste heat from data centers: An investment analysis. https://www.researchgate.net/publication/328590267
25. Dominković, Stunjek, Blanco, Madsen, Krajačić, Technical, economic and environmental optimization of district heating expansion in an urban agglomeration. https://www.bib.irb.hr/1084867
