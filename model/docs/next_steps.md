# Next steps

Open model improvements, in order of priority. Status as of November 2026.

1. **Rolling planning** (implemented, `cph-dispatch rolling`): daily re-planning with a
   seven-day (or 24-hour) look-ahead. Planning inputs are currently the actual 2024 data;
   replace them with Varmelast's 2024 forecasts once available (requested).
2. **HTF demand for 2024** (done, `data/processed/htf_demand_2024/`): the 2019 profile is
   transferred with a degree-day fit (base 13.8 MW, 3.84 MW/K below 16.25 C, daily
   R2 0.75) to 2024 temperatures and scaled to 377.3 GWh (factor 1.10). Peak 126.7 MW in
   the January 2024 cold spell; the HX capacity is raised to the peak where needed
   (`hx.cover_peak`). The 2019 profile responds only weakly to temperature within a month
   (seasonal pattern dominates), so measured hourly HTF data remain preferable.
3. **Local generation at HTF** (on hold until HTF confirms how the units are operated):
   add data-centre heat pumps (Nordea, GlobalConnect), other heat recovered from cooling
   and solar heat as fixed local supply; calibrate City2 and Mølleholmen against their
   actual output (Mølleholmen 4.0 GWh in 2025 vs. 8.8 GWh in the model).
4. **Electricity costs for HTF's heat pumps and pumping**: replace the provisional
   125 DKK/MWh adder with HTF's actual tariffs and taxes.
5. **Planned 2024 schedules from Varmelast**: compare planned with measured operation.
