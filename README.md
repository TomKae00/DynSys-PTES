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
