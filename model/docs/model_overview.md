# How the model works — short overview

This is the one-page walkthrough. Details are in [formulation.md](formulation.md),
the pricing logic in [research_workflow.md](research_workflow.md).

## The question each run answers

For one horizon (e.g. one week) and one tariff: *if HTF minimises its own bill
under this tariff, what does that cost the whole heat system, and who gains or
loses compared with today's monthly tariff?*

## Two networks, one builder

`optimisation.build()` creates a PyPSA network in one of two modes:

| Mode | What is in the network | Objective |
|---|---|---|
| `objective: system` | Copenhagen supply (CHPs, waste, boilers, regional HPs, AMV/AVV accumulators), HX, PTES, local HPs, HTF demand | Fuel + O&M + electricity purchases (+adder) − electricity sales + HP starts. Heat payments are *not* costs here. |
| `objective: local` | Only HTF's side: HX, PTES, local HPs, HTF demand. Upstream is a free heat source. | HTF's bill: τ·HX + (τ − δ)·discharge + HP electricity + discharge pumping + HP starts |

`add_constraints()` adds the PTES rules (modes, minima, ramps, 2 h no-reversal,
fixed end inventory) and HP commitment to both.

## The four stages of one comparison (`workflow.py`, `study.py`)

```
1  central = solve(system network)                         -> coordinated schedule
   prices  = same network as LP with binaries fixed         -> mu_t (upstream heat), v_t (PTES inventory)
2  credit  = tariffs.candidate_credit(central, spec)        -> delta_t for this tariff
3  local   = solve(local network,  charging <= central charging, credit delta_t)
                                                            -> HTF RESPONSE
4  corrective = solve(system network, HTF's HX/discharge/HP fixed, charging <= central charging)
                                                            -> system cost of that response
```

**Where the HTF response comes from (stage 3):** the local network contains only
HTF's assets. Upstream heat is a free generator at the CPH bus, so HTF pays only
through the link costs: the HX link costs τ per MWh, the discharge link costs
τ − δ_t plus pumping, the HP links cost spot + adder. Charging is free for HTF
(upstream pays for it) but capped at the central charging schedule, and the PTES
must end at 1,500 MWh. HTF's cheapest solution under these prices **is** the
response: how much it discharges and when, how much HX heat it takes, and when
its HPs run. Nothing behavioural is added; it is a rational cost-minimising
response.

**Stage 4** then asks what the upstream system has to do given that response.
It fixes HTF's HX, discharge and HP heat to the stage 3 values and re-optimises
all upstream units and accumulators. Charging can still be reduced within the
announced slots (e.g. if HTF discharged less, there is less to refill).

**Reference.** Two options (`reference` in the config):

- `metered_2024` (paper default): the **measured 2024 operation**. PTES charging and
  discharging are fixed to the metered hourly flows (no design limits or operating
  rules apply to measured data); HTF chooses HX import and its HPs under the monthly
  tariff; stage 4 re-dispatches Copenhagen around it. The model's monthly-tariff
  response (δ = 0) is then reported as an extra row, `monthly_response`.
- `monthly_response`: stages 3–4 with δ = 0 as the reference.

**PTES end inventory.** With `ptes.endpoints: measured`, every case starts and ends
each period at the measured 2024 inventory (not cyclic). If the metered replay ends
slightly off that level under the model's loss rate, the difference is valued at the
coordinated schedule's final stored-heat value (`terminal_inventory_adjustment_dkk`).

**Waste.** `waste_policy: observed_must_run` burns waste as observed in 2024; only heat
above Copenhagen's minimum need is cooled (340 h in 2024).

## The numbers in `study.csv`

For each tariff versus the reference (`workflow.benefits`):

| Column | Meaning |
|---|---|
| `system_operating_cost_saving_dkk` | ΔC_sys: corrective cost(reference) − corrective cost(tariff). Welfare proxy. |
| `local_bill_saving_dkk` | ΔB_HTF: HTF bill(reference) − HTF bill(tariff) |
| `aggregate_upstream_operating_surplus_change_dkk` | ΔU = ΔC_sys − ΔB_HTF: VEKS/producers as one account (heat revenue change + cost change) |
| `system_cost_change_from_coordinated_dkk` | Gap to the stage 1 optimum; for the reference this is the full coordination value |
| `aggregate_participation_screen` | True if ΔB_HTF ≥ 0 and ΔU ≥ 0 (both sides win) |

Transfers cancel in ΔC_sys, so ΔB_HTF + ΔU = ΔC_sys exactly.

## Tariff families (`tariffs.py`)

| Family | Credit δ_t |
|---|---|
| `constant` | fixed level |
| `bounded_mean_matched_value` | value spread μ/r − v scaled by g, clipped to [0, 10], monthly mean = level |
| `shared_value` | share s of the positive spread: max(0, s·(μ/r − v/η)) |
| `heat_value_price`, `inventory_value_price` | absolute discharge prices at μ/r or v/η |

`direct_basis: monthly_mean_matched_marginal` additionally makes direct HX heat
hourly (τ + μ/r − monthly mean), so HTF's HPs see the system heat value.

## Running the paper cases

```sh
# once: hourly metered PTES flows + measured inventory
cph-dispatch metered --raw-ptes "../hoje Taastrup data/ptes_operation_data_hoje_taastrup_2024.csv" \
  --observations ../Data/ptes_operation_data_hourly.csv
# full year in one horizon (Gurobi)
cph-dispatch study --solver gurobi --time-limit 7200 --study-spec config/paper_annual_2024.yaml \
  --local-profiles data/processed/profiles_2024/local_profiles.csv \
  --metered data/processed/ptes_metered_2024.csv --output results/runs/annual_2024
```

## Running

```sh
cph-dispatch study --solver highs --study-spec config/paper_weekly_2024.yaml \
  --local-profiles data/processed/profiles_2024/local_profiles.csv \
  --output results/runs/weekly_2024
```

One 168 h week with three tariffs takes about 30–40 s with HiGHS.
