#!/usr/bin/env python3
import logging
import pandas as pd
import atlite
from pathlib import Path

CUTOUT_PATH = Path("cutouts/ht_region_era5_2013.nc")

START = "2013-01-01 00:00:00"
END   = "2014-01-01 00:00:00"
FREQ  = "h"

LON_MIN, LON_MAX = 11.8, 12.9
LAT_MIN, LAT_MAX = 55.2, 56.1

def main():
    logging.basicConfig(level=logging.INFO)
    CUTOUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    time = pd.date_range(
        START, END,
        freq=FREQ,
        inclusive="left"
    )

    cutout = atlite.Cutout(
        path=str(CUTOUT_PATH),
        module="era5",
        x=slice(LON_MIN, LON_MAX),
        y=slice(LAT_MIN, LAT_MAX),
        time=time,
    )

    print(f"Preparing cutout: {CUTOUT_PATH}")
    cutout.prepare(features=["influx", "temperature"])
    print("Done.")

if __name__ == "__main__":
    main()