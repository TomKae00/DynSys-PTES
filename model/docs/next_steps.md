# Next steps

Open model improvements, in order of priority. Status as of November 2026.

1. **Rolling planning** (implemented, `cph-dispatch rolling`): daily re-planning with a
   seven-day (or 24-hour) look-ahead. Planning inputs are currently the actual 2024 data;
   replace them with Varmelast's 2024 forecasts once available (requested).
2. **HTF demand for 2024**: rescale the 2019 profile with 2019 and 2024 temperatures
   (base load plus heating-degree term, hour and weekday pattern kept) to the 377.3 GWh
   supplied to HTF's network in 2024. Needs 2019 ERA5-Land temperatures. Replace with
   measured hourly HTF data if HTF provides it.
3. **Local generation at HTF** (on hold until HTF confirms how the units are operated):
   add data-centre heat pumps (Nordea, GlobalConnect), other heat recovered from cooling
   and solar heat as fixed local supply; calibrate City2 and Mølleholmen against their
   actual output (Mølleholmen 4.0 GWh in 2025 vs. 8.8 GWh in the model).
4. **Electricity costs for HTF's heat pumps and pumping**: replace the provisional
   125 DKK/MWh adder with HTF's actual tariffs and taxes.
5. **Planned 2024 schedules from Varmelast**: compare planned with measured operation.
