#!/usr/bin/env python3
import atlite
from pathlib import Path

CUTOUT_PATH = Path("cutouts/ht_region_era5_2013.nc")

def get_pv_p_max_pu_profile(cutout_path):
    """
    Load an existing atlite cutout and return one aggregated hourly
    PV p_max_pu profile for the whole cutout region.
    """
    cutout = atlite.Cutout(str(cutout_path))

    # Per-unit PV generation for each grid cell
    pv_cf = cutout.pv(
        panel="CSi",
        orientation="latitude_optimal",
        per_unit=True,
    )

    # Aggregate all spatial cells to one regional profile
    spatial_dims = [dim for dim in pv_cf.dims if dim != "time"]
    pv_profile = pv_cf.mean(dim=spatial_dims)

    # Convert to pandas Series
    pv_profile = pv_profile.to_series()
    pv_profile.name = "p_max_pu"

    return pv_profile


def main():
    pv_profile = get_pv_p_max_pu_profile(CUTOUT_PATH)

    print(pv_profile.head())
    print(pv_profile.describe())

    # Save for later use
    pv_profile.to_csv("pv_p_max_pu_hoje_taastrup.csv", header=True)


if __name__ == "__main__":
    main()