"""Recorded PTES context, explicitly distinguishing meters from inventory differences."""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


def load_observations(path, *, kind):
    if kind not in ("soc_proxy", "metered"):
        raise ValueError("Declare observation kind as soc_proxy or metered")
    frame = pd.read_csv(path, index_col="time")
    frame.index = pd.to_datetime(frame.index, utc=True)
    if frame.index.has_duplicates or not np.all(np.diff(frame.index.asi8) == 3600 * 10**9):
        raise ValueError(
            "Recorded data must have unique consecutive UTC hours; no automatic filling"
        )
    columns = ["Q_storage_mwh", "E_charge_mwh", "E_discharge_mwh"]
    if len(frame) < 2 or not np.isfinite(frame[columns]).all().all():
        raise ValueError("Recorded data must contain finite inventory and hourly energies")
    if (frame[columns] < -1e-8).any().any():
        raise ValueError("Recorded inventory and directional energies must be nonnegative")
    difference = frame.Q_storage_mwh.diff().iloc[1:]
    charge, discharge = frame.E_charge_mwh.iloc[1:], frame.E_discharge_mwh.iloc[1:]
    inferred = bool(
        np.allclose(charge, difference.clip(lower=0), atol=1e-7, rtol=1e-8)
        and np.allclose(discharge, -difference.clip(upper=0), atol=1e-7, rtol=1e-8)
    )
    if kind == "metered" and inferred:
        raise ValueError(
            "Charge/discharge exactly equal SOC differences; cannot label these as metered flows"
        )
    result = frame[columns].rename(
        columns={
            "Q_storage_mwh": "recorded_inventory_mwh",
            "E_charge_mwh": "recorded_charge_mwh",
            "E_discharge_mwh": "recorded_discharge_mwh",
        }
    )
    metadata = {
        "path": str(path),
        "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "declared_kind": kind,
        "flows_match_inventory_difference": inferred,
        "hours": len(frame),
        "timezone": "UTC",
        "interpretation": (
            "Inventory-difference proxy: includes losses/temperature effects, not metered throughput"
            if kind == "soc_proxy"
            else "User-declared hourly metered energy; provenance requires verification"
        ),
    }
    return result, metadata


def metered_ptes(raw_path, inventory_path):
    """Hourly metered PTES flows (UTC) from the 10-minute operation file.

    E_charge/E_discharge are metered energy per 10-minute interval [MWh]; their
    hourly sums are average MW. Inventory is the temperature-based energy content
    at the end of each hour (the hourly file's Q_storage_mwh).
    """
    raw = pd.read_csv(raw_path, index_col=0, usecols=["time", "E_charge", "E_discharge"])
    raw.index = pd.to_datetime(raw.index, utc=True)
    if raw.index.has_duplicates or not np.isfinite(raw).all().all() or (raw < 0).any().any():
        raise ValueError("Metered PTES energies must be unique, finite and nonnegative")
    hourly = raw.resample("h").sum(min_count=1)
    if hourly.isna().any().any():
        raise ValueError("Metered PTES data has empty hours; no automatic filling")
    inventory = pd.read_csv(inventory_path, index_col="time").Q_storage_mwh
    inventory.index = pd.to_datetime(inventory.index, utc=True)
    frame = pd.DataFrame(
        {
            "metered_charge_mw": hourly.E_charge,
            "metered_discharge_mw": hourly.E_discharge,
            "measured_inventory_mwh": inventory.reindex(hourly.index),
        }
    )
    if frame.isna().any().any():
        raise ValueError("Metered flows and measured inventory must cover the same UTC hours")
    frame.index.name = "timestamp"
    return frame


def compare_observations(dispatch, observations, metadata):
    """Compare only matched hours; never scale demand or invent a fixed-dispatch replay."""
    matched = dispatch.index.intersection(observations.index)
    if len(matched) < 2:
        raise ValueError("Recorded and model results need at least two overlapping UTC hours")
    joined = dispatch.loc[matched, ["ptes_energy_mwh", "ptes_charge_mw", "ptes_discharge_mw"]].join(
        observations.loc[matched]
    )
    report = {
        **metadata,
        "compared_hours": len(matched),
        "model_hours_without_observations": len(dispatch) - len(matched),
        "model_inventory_mean_mwh": float(joined.ptes_energy_mwh.mean()),
        "recorded_inventory_mean_mwh": float(joined.recorded_inventory_mwh.mean()),
        "recorded_charge_mwh_on_matched_hours": float(joined.recorded_charge_mwh.sum()),
        "recorded_discharge_mwh_on_matched_hours": float(joined.recorded_discharge_mwh.sum()),
        "model_charge_mwh_on_matched_hours": float(joined.ptes_charge_mw.sum()),
        "model_discharge_mwh_on_matched_hours": float(joined.ptes_discharge_mw.sum()),
        "comparison_role": "Historical context; remapped demand and modelled losses prevent causal tariff attribution",
    }
    return joined, report
