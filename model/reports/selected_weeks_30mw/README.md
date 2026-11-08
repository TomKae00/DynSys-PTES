# Selected-week tariff findings — 30 MW charging/discharging

This is the **versioned evidence snapshot** for the current findings. It is small
enough to travel with the source branch; full networks and raw inputs remain in
Git-ignored local run directories. Snapshot organised 8 November 2026.

## Main finding

One tested value-informed hourly discharge tariff, bounded to a 0–10 DKK/MWh
reduction with a sampled-month arithmetic mean of 5, increases utilisation and
benefits both HTF and the model's upstream aggregate in the three selected weeks.
Direct heat stays monthly. These are **scenario operating benefits**, not an annual
welfare result, an empirically fitted tariff or identified supplier profit.

| Selected 2024 week | Discharge MWh | HTF saving DKK | Upstream aggregate gain DKK | Joint operating saving DKK |
|---|---:|---:|---:|---:|
| Winter, 8–14 January | 1,390.34 | 3,023.68 | 3,466.02 | 6,489.70 |
| Shoulder, 15–21 April | 1,865.20 | 12,327.38 | 83,079.82 | 95,407.20 |
| Summer, 15–21 July | 577.73 | 2,815.26 | 10,823.75 | 13,639.02 |

The detailed [findings note](../../docs/findings_30mw.md) explains the constant-5
control, both hourly strengths, lossless sensitivity, solver bounds and failed
participation cases. Do not add stakeholder gains to joint savings again or
extrapolate these weeks to annual cycles/benefits.

## Contents

| File | Purpose |
|---|---|
| [base.pdf](base.pdf), [base.png](base.png), `base.svg` | Current comparison figure, including both tested hourly strengths |
| [ptes_lossless.pdf](ptes_lossless.pdf), `ptes_lossless.png`, `ptes_lossless.svg` | Zero-PTES-standing-loss sensitivity figure |
| [base.csv](base.csv), [ptes_lossless.csv](ptes_lossless.csv) | All candidate outcomes, transfers, solver gaps and utilisation |
| `base_config.yaml`, `ptes_lossless_config.yaml` | Exact central-scenario assumptions used in these runs |
| `base_spec.yaml`, `ptes_lossless_spec.yaml` | Executed periods, controls and hourly candidate parameters |
| `evidence.json` | Source hashes, price ranges and independently reconciled cost/energy changes |
| `provenance.json` | Original input/runtime fingerprints for each source run |
| `historical_2024_audit.json` | SOC-proxy audit; not a metered annual baseline |
| `checksums.sha256` | Integrity checks for this snapshot |

The 2024 historical file yields 9.63 proxy equivalent discharge cycles; its flow
columns are inventory differences. The reported roughly eight cycles still needs
its source/definition reconciled. Demand remains a remapped 2019 template, pumping
is provisional, and the selected-week optimisations use perfect foresight and
fixed common inventories.

## Reproduce or inspect

From `model/`, use the package [instructions](../../README.md) and canonical
[study configurations](../../config/README.md). The preserved full runs are
`results/findings_30_30_pump005/` and `results/findings_30_30_pump005_lossless/`.
Regenerate into a **fresh** directory, using the snapshot's `*_config.yaml` and
`*_spec.yaml` with the CLI's `--config` and `--study-spec` arguments if defaults change.

```sh
cd reports/selected_weeks_30mw
sha256sum -c checksums.sha256
```

Saved runtime source fingerprints predate subsequent formatting/organisation;
solver tolerances and alternative optima can affect schedules on a new run.
Original result metadata was not rewritten. No full networks or raw operational
series are included in this compact snapshot. Earlier local experiments are indexed
under `results/archive/2026-11-08/`, separate from these current results.
