# Copenhagen dispatch and HTF response in PyPSA

This package builds real **PyPSA networks**, using native buses, generators, loads,
links and stores. Custom Linopy constraints implement CHP coupling and PTES rules.
HiGHS and optional Gurobi are selected through PyPSA's solver interface. The former
standalone sparse-matrix solver is not part of this branch.

The hourly optimisation has fixed capacities. Its inputs and financial assumptions
represent a research scenario, not a calibrated reconstruction of Varmelast.
See [formulation](docs/formulation.md), [data sources](docs/data_sources.md) and
[validation](docs/validation.md) for the limits of numerical interpretation.

## Install and run

From this directory, use Python 3.12 in a clean environment:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-tested.txt
pip install -e . --no-deps
pytest -q
cph-dispatch demo --hours 48 --prices --output results/demo
```

The tested PyPSA/Linopy/xarray versions are pinned together. The demo is explicitly
synthetic and works offline; failed downloads never fall back to invented inputs.
Generated inputs and results are ignored by git. Use an empty output directory for
each run. The CLI publishes a result directory only after all its solves and exports
succeed, and refuses to overwrite an existing result.

Prepare the 2024 public inputs and solve diagnostic weeks:

```sh
cph-dispatch prepare --year 2024
# Strict preparation rejects gaps; the documented opt-in policy records each repair:
cph-dispatch prepare --year 2024 --repair
cph-dispatch solve --start 2024-01-08T00:00Z --hours 168 --prices --output results/winter
cph-dispatch solve --start 2024-07-15T00:00Z --hours 168 --prices --output results/summer
```

An accepted solve writes `network.nc`, `dispatch.csv` and `summary.json`. The summary
contains the scenario, versions, input hashes, objective components, solver gap/bound
and independent feasibility checks. Prices are **conditional LP values with integer
commitments fixed**. Raw MILP bus prices are cleared; use `--prices` to populate the
network's bus prices and the CSV's upstream value column. Custom PTES modes are
recorded in both the CSV and the links' status table.

Read and inspect an exported network with ordinary PyPSA:

```python
import pypsa
n = pypsa.Network("results/winter/network.nc")
n.links_t.p1
n.stores_t.e
n.buses_t.marginal_price
n.meta
```

Snapshots inside PyPSA are timezone-naive **UTC**, explicitly labelled in metadata;
CSV timestamps remain timezone-aware UTC. A network export preserves native
components and results, not the custom Linopy constraint callbacks. To re-solve,
use this package's builder and solve functions with the saved scenario and inputs.

## Central scheduling, HTF response and upstream adjustment

```sh
cph-dispatch compare --synthetic --hours 72 --discount 50 --prices --output results/coupled_demo
cph-dispatch compare --start 2024-01-08T00:00Z --hours 168 --discount 50 --output results/coupled_winter
```

The comparison performs five PyPSA solves: one coordinated schedule, zero-credit
HTF response and corrective upstream dispatch, then the supplied-credit HTF response
and its corrective dispatch. Each case has its own network/CSV/summary; the parent
folder contains `comparison.json`. Optional price extraction adds a continuous solve.
The 50 DKK/MWh value is an illustrative input, not a derived or optimal tariff.
An hourly `discharge_discount_dkk_mwh` input column can supply a varying candidate;
an explicit `--discount` overrides it. The reference always uses zero credit.

The default **curtailable charging** policy treats the announced central charging
schedule as an availability ceiling. The local solve chooses discharge and local
supply with a feasible charging trajectory. Corrective dispatch holds actual direct
supply, discharge and local HP heat fixed, and optimises compatible upstream charging
within that same ceiling. This assumes upstream charging can be reduced after a
local response; it is an analytical adaptation assumption requiring confirmation.
The corrective network is the authoritative physical charging/inventory trajectory.
All cases retain common initial and final inventories, without free depletion.

This removes the old requirement to discharge almost the entire planned charge
volume. The explicit `--charging-policy fixed` option retains the former experiment,
where charging and the final inventory nearly determine throughput. It is useful
for comparison but cannot establish freely chosen utilisation.

Direct HTF heat pays the monthly reference price. Discharge pays that price minus
the credit; charging heat belongs upstream. HTF expenditure and supplier local heat
revenue are reported separately from upstream operating expenditure. Supplier revenue
is not profit. A smaller HTF bill is not evidence of system savings: use corrective
operating-cost differences and their solver gap bounds. With zero pumping cost and
equal tariffs, HTF can be economically indifferent between discharge and direct heat;
an arbitrary optimal schedule must not be called observed behaviour.

Individual local solves remain available:

```sh
cph-dispatch solve --hours 168 --output results/central
cph-dispatch solve --hours 168 --objective local --schedule results/central/dispatch.csv \\
  --discount 50 --charging-policy curtailable --output results/local_response
```

## Annual solves and settings

```sh
cph-dispatch solve --relax --time-limit 120 --output results/annual_lp
pip install -e '.[gurobi]'
cph-dispatch solve --solver gurobi --time-limit 1800 --prices --output results/annual_gurobi
```

Gurobi needs a licence covering the full model size. See the validation record for
which annual cases completed; small-case solver equivalence is not an annual result.
Solver time limits apply per solve and are not strict process wall limits. For a hard
local budget, wrap the command with a process timeout. `--relax` requests a labelled
LP diagnostic, not an integer PTES operating schedule. `--mip-gap` changes the relative
gap target; absolute gaps are also reported.

Local HPs are dispatchable by default. `--hp-policy must_run` is an explicit full
thermal-output scenario, assumed already operating at the start; actual must-run
profiles still require stakeholder data. PTES power, losses, pumping and network
losses remain configurable, provisional assumptions. The 12-hour full-charge to
full-discharge rule is still not implemented because its operational definition
requires clarification. CHP commitment and regional accumulator modes remain relaxed.

## Code structure and migration

| File | Responsibility |
|---|---|
| `src/cph_dispatch/data.py` | Public downloads, UTC alignment, bounded repairs and inherited templates |
| `src/cph_dispatch/optimisation.py` | PyPSA components, custom constraints, solving and conditional prices |
| `src/cph_dispatch/results.py` | Independent physical extraction and financial accounting |
| `src/cph_dispatch/workflow.py` | Announced schedule, tariff responses and corrective dispatch |
| `src/cph_dispatch/cli.py` | Commands, provenance and atomic network/CSV/JSON exports |
| `config/base.yaml`, `config/plants.csv` | Explicit scenario and plant parameters |
| `tests/` | Physical, economic, solver-equivalence and data regression checks |

This implementation was transferred from `TomKae00/DynSys-Dynamic-Tariff` at
`17c8261c10ad5fc8f31ca41464078f95959b360b` into the modelling repository.
Its upstream PyPSA migration started at `c57c2d44b5f8db0a5347a836c683f66933f1916a`
of that repository's Copenhagen extension. The original HTF constraints and inherited inputs trace back to
`TomKae00/DynSys-PTES` at `48e49c0b8dc6415611cf0ed6ce985ea3b2d1ef50`.
A pinned numeric fixture checks three objectives against the direct formulation,
with bypass disabled to isolate framework equivalence. A separate test validates
the corrected full heat-only bypass capacity. The prior interpretation had incorrectly
used only the extra bypass capacity as a ceiling for the whole heat-only mode.
The PyPSA first-hour storage loss is explicit, preserving the same physical inventory
balance as the direct formulation. Input economics and demand assumptions are retained.
