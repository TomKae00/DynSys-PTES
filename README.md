# Copenhagen PyPSA extension

The current Copenhagen dispatch, HTF response and corrective-dispatch workflow is
in [model/](model/README.md), on branch `feature/copenhagen-pypsa`.

```sh
cd model
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-tested.txt
pip install -e . --no-deps
cph-dispatch demo --hours 48 --prices --output results/demo
```

See [model validation](model/docs/validation.md) for completed checks and the annual
MILP runtime limit. The implementation was transferred from
`TomKae00/DynSys-Dynamic-Tariff` at `17c8261c10ad5fc8f31ca41464078f95959b360b`.
The original scripts and datasets remain available below for historical analysis.

---

# PTES in Copenhagen District Heating (PyPSA-based Analysis)

This repository contains a Python-based workflow to model a **Pit Thermal Energy Storage (PTES)** system integrated into a **district heating subsystem of Copenhagen**. The main goal is to evaluate the operation, flexibility, and system benefits of PTES using **PyPSA** as the underlying energy system modeling framework.

## Objectives

- Represent PTES within a PyPSA-based district heating model
- Load and explore existing data (demand, generation, temperatures, etc.)
- Prepare input data for integration into a PyPSA network
- Run and analyze simulations to assess:
  - Storage operation (charging/discharging)
  - Impact on heat production portfolio
  - System-level indicators (costs, fuel use, emissions, etc.)

## Repository Structure (proposed)

```text
ptes-cph/
├─ README.md
├─ environment.yml         # or requirements.txt for Python dependencies
├─ data/
│  ├─ raw/                 # Original input data (CSV/Excel/…)
│  └─ processed/           # Cleaned / preprocessed data for modeling
├─ notebooks/              # Jupyter notebooks for exploration and plotting
├─ src/
│  ├─ __init__.py
│  ├─ config.py            # Paths, constants, simple config
│  ├─ data_loading.py      # Functions to load & inspect data
│  ├─ preprocessing.py     # Data cleaning and transformations
│  └─ modeling/
│     ├─ build_network.py  # Build/extend PyPSA network with PTES
│     └─ run_scenarios.py  # Run and compare scenario results
└─ scripts/
   └─ load_data.py         # CLI entry point for initial data loading
