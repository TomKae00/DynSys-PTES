# Copenhagen dispatch and HTF/PTES tariff model

This package builds native **PyPSA networks with custom Linopy constraints**.
Capacities are fixed; decisions concern hourly operation. Central scheduling,
HTF's local response and upstream corrective dispatch are separate optimisations.

## Current status

- Research solver: **Gurobi**, eight threads.
- PTES: **3,300 MWh, 30 MW delivered charging and 30 MW delivered discharge**.
- Pumping: **0.005 MWh electricity per charged/discharged MWh**, provisional.
- Evidence: three selected 168-hour periods, constant/hourly tariff controls and
  a zero-PTES-standing-loss sensitivity. No new annual integer result is claimed.

Start with the [versioned results snapshot](reports/selected_weeks_30mw/README.md),
[findings](docs/findings_30mw.md), [configuration index](config/README.md) and
[local run index](results/README.md). Old pilots are archived, not current evidence.

## Installation and checks

From this directory, using Python 3.12:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-tested.txt
pip install -e '.[gurobi,analysis]' --no-build-isolation
ruff check src tests
ruff format --check src tests
pytest -q
```

The tested PyPSA/Linopy/xarray versions are pinned together. Gurobi needs a suitable
licence; `--solver highs` explicitly selects the portable alternative. There is no
automatic solver fallback. CI uses HiGHS and skips unavailable optional Gurobi checks.

The offline demo never substitutes synthetic data for failed real-data preparation:

```sh
cph-dispatch demo --hours 48 --solver gurobi --prices --output results/runs/demo
cph-dispatch compare --synthetic --hours 48 --solver gurobi --discount 5 \
  --output results/runs/synthetic_compare
```

Always choose a fresh result directory. Accepted network/CSV/JSON trees are
published atomically, and existing results are not overwritten.

## Prepare the 2024 inputs

Original ERA5 files are retained in `../Data/`. Rebuild their temperature/COP
profiles in the canonical generated-input location:

```sh
cph-dispatch profiles --year 2024 --era5-files ../Data/era5_land_t2m_2023_12_31.nc \
  ../Data/era5_land_t2m_2024_*.nc --output data/processed/profiles_2024
cph-dispatch prepare --year 2024 --repair
```

The existing local `data/processed/profiles_2024/` was relocated from the earlier
`results/review_profiles_2024/` without changing its content. Skip regeneration if
using that accepted cache. An ambient CSV with `time,temperature_c` and 23 preceding
UTC hours is an alternative to `--era5-files`.

Preparation is strict unless `--repair` is supplied; bounded repairs and downloads
are hashed/logged. Prepared inputs without `--local-profiles` retain legacy COP
mapping for historical benchmark reproduction. The current experiments instead
supply the weather-derived profiles at solve time, preserving the original prepared
input file and using actual UTC alignment:

```sh
cph-dispatch study --solver gurobi --study-spec config/tariff_findings_30mw.yaml \
  --local-profiles data/processed/profiles_2024/local_profiles.csv \
  --figures --output results/runs/findings_base
cph-dispatch study --solver gurobi --study-spec config/tariff_findings_lossless_30mw.yaml \
  --local-profiles data/processed/profiles_2024/local_profiles.csv \
  --figures --output results/runs/findings_ptes_lossless
```

The snapshot also includes the exact executed specifications and configuration
copies. Use those with `--config` when reproducing after defaults change.

## Tariff comparison and accounting

Each physical scenario reuses one coordinated schedule and one zero-credit local/
corrective reference. Every candidate gets its own local response and corrective
system solve. `study.csv` retains every candidate; `study.json` states the tested
family, selection criterion and limitations. Inventories share fixed endpoints.

The default discharge-service boundary bills HTF for direct heat and discharge,
with upstream paying charging heat/charging pumping and HTF paying discharge
pumping. This remains a contractual assumption. Curtailable charging is limited
by the announced central schedule, and actual direct supply, discharge and HP heat
remain fixed in corrective dispatch. That is an adaptation assumption, not a
behavioural equilibrium or actual balancing-market settlement.

Heat payments and discharge credits are transfers. They are excluded from system
operating expenditure. HTF savings and upstream aggregate surplus changes reconcile
to joint operating savings; revenue is not profit, and the aggregate is not a legal
actor. Conditional marginal values are not contractual heat prices. See the
[annual pricing design](docs/annual_tariff_study.md) and [formulation](docs/formulation.md).

For a standalone supplied-credit comparison or reference ambiguity diagnostic:

```sh
cph-dispatch compare --start 2024-01-08T00:00Z --hours 168 --discount 5 \
  --solver gurobi --prices --response-range --output results/runs/winter_compare
cph-dispatch report --run results/runs/winter_compare \
  --observations ../Data/ptes_operation_data_hourly.csv --observation-kind soc_proxy \
  --output results/runs/winter_figures
```

`--response-range` adds two throughput-extremum solves within 0.01 DKK of accepted
HTF expenditure. The recorded charge/discharge file is identified as SOC-difference
proxies, not independent metered flows; reports compare it as historical context
without inflating demand or forcing proxy operation.

## Outputs and scientific limits

Full runs in `results/` are ignored by Git. The compact, frozen report in `reports/`
is intentionally versioned. It contains both hourly strengths and all constant
controls, not just successful cases. To regenerate the combined figure from its
saved table without downloading or solving:

```python
import pandas as pd
from cph_dispatch.plotting import plot_tariff_findings

plot_tariff_findings(
    pd.read_csv("reports/selected_weeks_30mw/base.csv"),
    "results/runs/redrawn_base_figure",
)
```

Accepted solves archive `network.nc`, `dispatch.csv`, `summary.json`, `inputs.csv`
and `plants.csv`, including runtime/input hashes, configuration, feasibility and
solver gaps. CSV timestamps are aware UTC; PyPSA snapshots are naive UTC. Reloading
`network.nc` preserves results, not the custom Linopy callbacks; re-solving requires
this builder and its constraints. `--prices` fixes accepted modes for a continuous
conditional-value solve; raw MILP duals are not presented as valid prices.

`--relax` is a diagnostic LP, not an integer schedule. Solver limits apply per call.
The larger sensitivity design and annual/rolling extensions are not completed merely
because their commands exist. Confirm real demand, metered flows, pumping, contracts,
losses, endpoint treatment and HP restrictions before annual or societal-welfare claims.

## Code map

| Module | Responsibility |
|---|---|
| `profiles.py`, `data.py` | Temperature/COP equations, public inputs, time alignment and repairs |
| `optimisation.py` | Network construction, operational constraints, acceptance and conditional values |
| `results.py` | Physical extraction, losses and independent financial accounts |
| `workflow.py` | Coordinated schedule, local response, corrective dispatch and response range |
| `tariffs.py`, `study.py` | Candidate prices, mean/bound controls and matched experiments |
| `observations.py`, `analysis.py`, `plotting.py` | Evidence classification, reconciliation and figures |
| `cli.py` | Commands, provenance and atomic exports |

The [data sources](docs/data_sources.md), [validation](docs/validation.md),
[original migration audit](docs/research_workflow.md) and historical validation
notes retain the model's provenance. Root legacy scripts remain unchanged and
are used by temperature/COP parity tests. Manuscript work is in a separate repository.
