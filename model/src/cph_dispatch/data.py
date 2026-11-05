"""Explicit UTC alignment, traceable public downloads and bounded data repair."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd

TZ = "Europe/Copenhagen"
KEYS = {
    "ctr_mw": "BE-EO-CTR-EFF",
    "veks_mw": "DAP-VEKS-FORBRUG-EFF",
    "waste_available_mw": "BE-VL-AFFALD-EF",
}


def year_index(year):
    return pd.date_range(
        f"{year}-01-01", f"{year + 1}-01-01", freq="h", tz=TZ, inclusive="left"
    ).tz_convert("UTC")


def download(url, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = destination.with_suffix(destination.suffix + ".source.json")
    if destination.exists() and (
        not metadata_path.exists() or json.loads(metadata_path.read_text())["url"] != url
    ):
        raise ValueError(
            f"Cache provenance does not match query: {destination}; remove and fetch again"
        )
    if not destination.exists():
        with urlopen(url, timeout=90) as response:
            payload = response.read()
        # Atomic cache: interrupted downloads cannot become a valid cached input.
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(destination)
        metadata_path.write_text(
            json.dumps({"url": url, "retrieved_utc": datetime.now(UTC).isoformat()}, indent=2)
        )
    return {
        **json.loads(metadata_path.read_text()),
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "bytes": destination.stat().st_size,
    }


def repair_series(series, *, positive, repair, log, name):
    """Short gaps: linear interpolation. Outages <=48 h: adjacent-week mean.

    No extrapolation, no cascading imputations, and no unreported clipping.
    """
    series = series.astype(float).copy()
    invalid = ~np.isfinite(series) | (series.le(0) if positive else series.lt(0))
    series[invalid] = np.nan
    if not invalid.any():
        return series
    if not repair:
        raise ValueError(f"{name}: {invalid.sum()} invalid/missing hours; use --repair explicitly")
    original = series.copy()
    groups = invalid.ne(invalid.shift()).cumsum()
    for _, positions in series[invalid].groupby(groups[invalid]):
        indices = series.index.get_indexer(positions.index)
        start, end = indices[0], indices[-1]
        length = len(indices)
        if start == 0 or end == len(series) - 1 or length > 48:
            raise ValueError(
                f"{name}: cannot repair boundary or >48-hour gap at {positions.index[0]}"
            )
        if length <= 3:
            if pd.isna(original.iloc[start - 1]) or pd.isna(original.iloc[end + 1]):
                raise ValueError(f"{name}: interpolation lacks valid neighbours")
            values = np.linspace(original.iloc[start - 1], original.iloc[end + 1], length + 2)[1:-1]
            method = "linear_gap_at_most_3h"
        else:
            values = []
            for i in indices:
                neighbours = [i - 168, i + 168]
                if any(j < 0 or j >= len(series) or pd.isna(original.iloc[j]) for j in neighbours):
                    raise ValueError(f"{name}: outage has no two valid adjacent-week samples")
                values.append(float(original.iloc[neighbours].mean()))
            method = "adjacent_week_mean_gap_at_most_48h"
        for i, value in zip(indices, values, strict=True):
            series.iloc[i] = value
            log.append(
                {
                    "series": name,
                    "timestamp": str(series.index[i]),
                    "method": method,
                    "replacement": float(value),
                }
            )
    return series


def parse_varmelast(payload, year, *, repair=False):
    rows = []
    for entry in payload["times"]:
        row = {"timestamp": entry["timestamp"]}
        for label, key in KEYS.items():
            matches = [v for v in entry["values"] if v["key"] == key]
            if len(matches) != 1:
                raise ValueError(f"Expected one {key} at {row['timestamp']}")
            value = matches[0]
            row[label] = value["value"] if not value.get("valueError", 0) else np.nan
        rows.append(row)
    frame = pd.DataFrame(rows)
    frame.index = pd.to_datetime(frame.pop("timestamp"), utc=True)
    if frame.index.has_duplicates:
        raise ValueError("Duplicate Varmelast UTC timestamps")
    frame = frame.reindex(year_index(year))
    log = []
    for label in KEYS:
        frame[label] = repair_series(
            frame[label], positive=label != "waste_available_mw", repair=repair, log=log, name=label
        )
    frame["regional_demand_mw"] = frame.ctr_mw + frame.veks_mw
    return frame, log


def seasonal_template(series, snapshots):
    """Map naive seasonal templates in fixed CET, explicitly copying Feb 28 to Feb 29.

    These inherited inputs lack DST provenance; do not silently localise them as observations.
    """
    series = series.copy()
    series.index = pd.to_datetime(series.index)
    if series.index.tz is not None or series.index.has_duplicates or series.isna().any():
        raise ValueError("Seasonal template must be complete, unique and timezone-naive")
    expected = pd.date_range(series.index[0], series.index[-1], freq="h")
    if not series.index.equals(expected) or len(series) not in (8760, 8784):
        raise ValueError("Seasonal template must contain one complete hourly year")
    mapping = {(t.month, t.day, t.hour): v for t, v in series.items()}
    result = []
    for t in snapshots.tz_convert("Etc/GMT-1"):
        key = (t.month, t.day, t.hour)
        if key not in mapping and t.month == 2 and t.day == 29:
            key = (2, 28, t.hour)
        result.append(mapping[key])
    return np.asarray(result, dtype=float)


def prepare(root, year=2024, *, repair=False):
    root = Path(root)
    raw = root / "data/raw"
    index = year_index(year)
    sources = {}
    vl_url = "https://www.varmelast.dk/api/v1/heatdata/historical?" + urlencode(
        {
            "from": f"{year}-01-01",
            "to": f"{year}-12-31",
            "intervalMinutes": 60,
            "contextSite": "varmelast_dk",
        }
    )
    vl_path = raw / f"varmelast_{year}.json"
    sources["varmelast"] = download(vl_url, vl_path)
    frame, repairs = parse_varmelast(json.loads(vl_path.read_text()), year, repair=repair)
    el_url = "https://api.energidataservice.dk/dataset/Elspotprices?" + urlencode(
        {
            "start": str((index[0] - pd.Timedelta(days=1)).date()),
            "end": str((index[-1] + pd.Timedelta(days=2)).date()),
            "filter": json.dumps({"PriceArea": ["DK2"]}),
            "limit": 10000,
        }
    )
    el_path = raw / f"dk2_{year}.json"
    sources["dk2"] = download(el_url, el_path)
    records = json.loads(el_path.read_text())["records"]
    electricity = pd.DataFrame(records)
    electricity.index = pd.to_datetime(electricity.HourUTC, utc=True)
    if electricity.index.has_duplicates:
        raise ValueError("Duplicate electricity prices")
    # Energy Data Service date filters use Danish wall time: request an extra day
    # if necessary, then align solely by the explicit HourUTC field.
    missing = frame.index.difference(electricity.index)
    if len(missing):
        raise ValueError(
            f"Electricity API did not cover {len(missing)} UTC hours; expand raw query"
        )
    frame["electricity_dkk_mwh"] = electricity.SpotPriceDKK.reindex(index)
    legacy = root / "data/legacy"
    demand = pd.read_csv(legacy / "htf_demand_2019.csv", index_col=0).demand_mw
    cop = pd.read_csv(legacy / "cop_2024.csv", index_col=0)
    frame["htf_demand_mw"] = seasonal_template(demand, index)
    for source, target in [("CITY2_HP", "city2_cop"), ("GW_HP", "groundwater_cop")]:
        frame[target] = seasonal_template(cop[source], index)
    tariff = pd.read_csv(legacy / "monthly_reference_2024.csv", index_col="month")
    frame["reference_tariff_dkk_mwh"] = [
        float(tariff.loc[t.month].iloc[0]) for t in index.tz_convert(TZ)
    ]
    for f in legacy.glob("*"):
        sources[f.name] = {"sha256": hashlib.sha256(f.read_bytes()).hexdigest()}
    report = {
        "year": year,
        "hours": len(frame),
        "timezone": "UTC",
        "model_year_timezone": TZ,
        "sources": sources,
        "repairs": repairs,
        "warnings": [
            "2019 HTF demand remapped; modelled COPs; inherited monthly reference",
            "CTR+VEKS metering boundary is not verified",
            "FFH50 is a planning study, not measured 2024 plant operation",
        ],
    }
    processed = root / "data/processed"
    processed.mkdir(parents=True, exist_ok=True)
    frame.to_csv(processed / f"inputs_{year}.csv", index_label="timestamp")
    (processed / f"quality_{year}.json").write_text(json.dumps(report, indent=2))
    return frame, report


def demo(hours=168):
    """Deliberately synthetic fixture; never substituted for a failed download."""
    index = pd.date_range("2024-01-08", periods=hours, freq="h", tz="UTC")
    t = np.arange(hours)
    return pd.DataFrame(
        {
            "ctr_mw": 0.65 * (1000 + 200 * np.cos(2 * np.pi * t / 24)),
            "veks_mw": 0.35 * (1000 + 200 * np.cos(2 * np.pi * t / 24)),
            "regional_demand_mw": 1000 + 200 * np.cos(2 * np.pi * t / 24),
            "htf_demand_mw": 35 + 10 * np.cos(2 * np.pi * t / 24),
            "waste_available_mw": 300.0,
            "electricity_dkk_mwh": 300 + 350 * np.sin(2 * np.pi * t / 24),
            "city2_cop": 3.4,
            "groundwater_cop": 3.2,
            "reference_tariff_dkk_mwh": 300.0,
        },
        index=index,
    )
