# Input provenance and evidence limits

## Public inputs

| Input | Source and use | Evidence limit |
|---|---|---|
| Hourly CTR and VEKS consumption | [Varmelast public historical data](https://www.varmelast.dk/), keys `BE-EO-CTR-EFF`, `DAP-VEKS-FORBRUG-EFF`; MJ/s = MW | Public metering boundary needs verification |
| Aggregate waste output | Same API, `BE-VL-AFFALD-EF` | Availability envelope, not plant-level measured availability |
| Hourly DK2 electricity | [Energi Data Service Elspotprices](https://www.energidataservice.dk/tso-electricity/Elspotprices), `SpotPriceDKK`, aligned using `HourUTC` | Observed electricity prices, exogenous to model |
| Main plant design points | [FFH50 assumptions workbook](https://varmeplanhovedstaden.dk/wp-content/uploads/2022/03/FFH50-forudsaetninger-FINAL.xlsx), `7_Værksdata grundlast` | Planning assumptions, not a 2024 as-built register |
| Peak capacity envelope | Same workbook, `7_Værksdata spidslast`, VEKS and CTR/HOFOR totals | 2025 planning values applied as a representative scenario |
| Regional accumulators | [Varmelast storage description](https://www.varmelast.dk/fjernvarmesystemet/brug-af-varmelagre) | Operator page capacities differ from planning assumptions |
| HTF demand, COP and monthly reference tariff | Pinned earlier research repository, `data/legacy/provenance.json` | Demand is 2019, COP is modelled, tariff contract unverified |

The API URL and raw-content SHA256 are recorded in the preparation quality report,
alongside retrieval time. Raw and processed files are generated rather than copied
into git. Cached downloads require matching query metadata. APIs can revise history;
retain the downloaded cache and report hashes with every published result.

FFH50 was released through the project in March 2022. Its assumptions include a
November 2021 assumptions note and an earlier demand forecast. Its hourly 2025,
2030 and 2050 profiles are **planning profiles**, not observed 2024 demand. This
implementation uses public 2024 Varmelast series instead of treating those forecast
profiles as observations. FFH50 remains useful for transparent plant parameters
and later demand/technology sensitivities.

## Normalised main portfolio

`config/plants.csv` transcribes design points and explicitly labels scenario cost
and availability fields. Main heat capacity excludes the separately listed bypass:

| Unit | Main heat MW | Extra bypass MW | Electricity MW | Fuel input MW | Representation |
|---|---:|---:|---:|---:|---|
| AMV1 | 250 | 68 | 68 | 338 | Shared-fuel backpressure/bypass |
| AMV4 | 400 | 150 | 150 | 487 | Shared-fuel backpressure/bypass |
| AVV1 | 370 | 0 | 260 | 652 | Extraction region |
| AVV2 | 450 | 0 | 345 | 804 | One aggregated main steam system |
| KKV8 | 51 | 8.5 | 8.5 | 56.667 | Shared-fuel backpressure/bypass |
| Waste fleet | 519.5 | — | Heat × 0.25 | — | ARC 190 + ARGO 136.5 + VF 192 MW |

The ARC one-line and two-line entries are alternatives. Only the two-line total
190 MW is counted. The FFH50 AVV2 gas turbine/straw mode rows are not independently
added to the main unit. Some workbook ratios are inconsistent with design points;
this code derives backpressure electricity efficiencies from explicit power/fuel
capacities and does not copy the inconsistent ARGO ratio. Site-level waste
electricity coupling is deliberately replaced by an aggregate scenario ratio.

Fuel prices, boiler efficiencies, O&M, availability factors, network losses,
regional HPs and electricity adders in the configuration are **scenario assumptions**.
They are not claimed to be confidential producer bids, audited contracts or a
historical 2024 fuel-price reconstruction. CO2/taxes are not separately calibrated.
Test them before deriving publishable tariffs.

## Time alignment and repairs

The model year is the Danish calendar year, represented by unique UTC timestamps.
For 2024 this is 2023-12-31 23:00 UTC through 2024-12-31 22:00 UTC: 8784 hours.
Electricity is joined by actual UTC timestamps, never by row number.

Preparation is strict by default. `--repair` enables this explicit policy:

1. Nonfinite values and nonzero API `valueError` flags are invalid. Nonpositive
   CTR/VEKS consumption is invalid; zero waste output remains valid.
2. Internal gaps up to three hours use linear interpolation between original valid
   neighbours. This includes the missing autumn repeated-hour sample.
3. Internal gaps of 4–48 hours use the average of original valid values one week
   before/after each affected hour. This covers the 39-hour public-data outage.
4. Longer gaps, missing endpoints or missing weekly neighbours are errors. Repairs
   do not feed subsequent repairs. Every replacement is individually logged.

The inherited HTF 2019 demand and naive COP files lack DST provenance. They are
treated as **fixed CET seasonal templates**, mapped by month/day/hour; Feb 29 copies
Feb 28. This assumption is distinct from converting timestamped observations and
must be replaced if true 2024 HTF demand becomes available. No SOC-difference proxy
is called measured charging/discharging. The earlier raw operational data and the
reported annual charge/discharge totals have not been used to fit this model.

## Dispatch-development report

The [EML dispatch report, August 2024](https://www.varmelast.dk/-/media/varmelast/dokumenter/eml-lastfordeling-efter-kontraktpriser-v2.pdf)
is a useful methodological reference. It describes a much more detailed 2030 LP
study using contract-price assumptions and appendix plant tables. Those assumptions
are not confidential actual bids, and the report's planning system is not the
observed 2024 system. This model borrows the idea of coordinated dispatch and
electricity-dependent CHP heat economics, while using a far smaller portfolio.
Its lossless storage assumptions are not copied into the HTF PTES.

Before submission, confirm the demand boundary, actual 2024 available capacities,
waste treatment, local charging/discharging settlement and pumping allocation;
then calibrate against independent measured energy and production totals. The
implementation provides that audit trail but does not establish empirical validity.
