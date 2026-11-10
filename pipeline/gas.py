"""Gas module: EIA monthly retail regular gasoline prices by city -> data/gas.json.

Source: EIA "Gasoline and Diesel Fuel Update" spreadsheet
PET_PRI_GND_A_EPMR_PTE_DPGAL_M.xls (no API key needed), "Cities" sheet.
EIA publishes city series for only 10 areas; each is mapped to a CBSA code.
All other metros are absent from the output and must be shown as missing.
Uses the latest month present in the file; a city with no value that month is
marked "missing" (no fallback to older months, states, or regions).

Usage:
  python pipeline/gas.py                 # download current file
  python pipeline/gas.py --file PATH     # use a local copy (.xls or .xlsx)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi
import pandas as pd

from tiers import method_entry, tag

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "eia"
OUT_PATH = ROOT / "data" / "gas.json"

URL = "https://www.eia.gov/dnav/pet/xls/PET_PRI_GND_A_EPMR_PTE_DPGAL_M.xls"
SOURCE_PAGE = "https://www.eia.gov/dnav/pet/pet_pri_gnd_a_epmr_pte_dpgal_m.htm"

# EIA series code -> (CBSA code, EIA area label)
SERIES_TO_CBSA = {
    "EMM_EPMR_PTE_YBOS_DPG": ("14460", "Boston, MA"),
    "EMM_EPMR_PTE_YORD_DPG": ("16980", "Chicago"),
    "EMM_EPMR_PTE_YCLE_DPG": ("17410", "Cleveland, OH"),
    "EMM_EPMR_PTE_YDEN_DPG": ("19740", "Denver"),
    "EMM_EPMR_PTE_Y44HO_DPG": ("26420", "Houston"),
    "EMM_EPMR_PTE_Y05LA_DPG": ("31080", "Los Angeles"),
    "EMM_EPMR_PTE_YMIA_DPG": ("33100", "Miami, FL"),
    "EMM_EPMR_PTE_Y35NY_DPG": ("35620", "New York City"),
    "EMM_EPMR_PTE_Y05SF_DPG": ("41860", "San Francisco"),
    "EMM_EPMR_PTE_Y48SE_DPG": ("42660", "Seattle, WA"),
}


# ---------- parsing ----------

def parse_value(raw) -> dict:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return {"value": None, "status": "missing"}
    try:
        v = float(str(raw).strip())
    except ValueError:
        return {"value": None, "status": "missing"}
    if v <= 0:
        return {"value": None, "status": "missing"}
    return {"value": round(v, 3), "status": "ok"}


def find_cities_sheet(path: Path) -> pd.DataFrame:
    """Return the raw grid (no header) of the sheet titled '...: Cities'."""
    book = pd.read_excel(path, sheet_name=None, header=None, engine="calamine")
    for grid in book.values():
        if grid.shape[0] > 3 and "Cities" in str(grid.iloc[0].tolist()):
            return grid
    raise ValueError(f"No 'Cities' sheet found in {path.name}")


def extract_latest(grid: pd.DataFrame) -> tuple[dt.date, dict]:
    """Grid layout: row 1 = series codes, row 2 = names, rows 3+ = date | values."""
    codes = [str(c).strip() for c in grid.iloc[1].tolist()]
    known = {i: c for i, c in enumerate(codes) if c in SERIES_TO_CBSA}
    if not known:
        raise ValueError("No known EIA city series codes found")
    data = grid.iloc[3:].copy()
    data[0] = pd.to_datetime(data[0], errors="coerce")
    data = data.dropna(subset=[0])
    value_cols = list(known)
    data = data[data[value_cols].notna().any(axis=1)]
    if data.empty:
        raise ValueError("No dated rows with values")
    row = data.loc[data[0].idxmax()]
    month = row[0].date().replace(day=1)

    metros = {}
    for col, code in known.items():
        cbsa, label = SERIES_TO_CBSA[code]
        metros[cbsa] = {"eia_area": label, "eia_series": code,
                        "price_per_gallon": tag(parse_value(row[col]), "observed", method_key(cbsa))}
    for code, (cbsa, label) in SERIES_TO_CBSA.items():  # series dropped from the file -> missing
        metros.setdefault(cbsa, {"eia_area": label, "eia_series": code,
                                 "price_per_gallon": tag({"value": None, "status": "missing"},
                                                         "observed", method_key(cbsa))})
    return month, dict(sorted(metros.items()))


def method_key(cbsa: str) -> str:
    return f"eia_gas_{cbsa}"


def build_methods(month: dt.date) -> dict:
    return {
        method_key(cbsa): method_entry(
            f"EIA monthly average retail price of regular gasoline for {label} (EIA city area mapped to this metro)",
            [{"source": "eia", "url": URL, "sheet": "Cities", "series": code}],
            month.strftime("%Y-%m"))
        for code, (cbsa, label) in SERIES_TO_CBSA.items()
    }


def build_output(metros: dict, month: dt.date, retrieved: dt.date) -> dict:
    return {
        "source": "U.S. Energy Information Administration (EIA), Gasoline and Diesel Fuel Update",
        "source_url": SOURCE_PAGE,
        "reference_period": month.strftime("%B %Y") + " (monthly average)",
        "as_of": month.strftime("%Y-%m"),
        "retrieved": retrieved.isoformat(),
        "basis": "Retail price of regular gasoline (all formulations), dollars per gallon, including taxes",
        "coverage_note": "EIA publishes city prices for only 10 areas; EIA's city sampling areas may not match "
                         "metro (CBSA) boundaries exactly. All other metros have no gas data.",
        "attribution": "Source: U.S. Energy Information Administration",
        "methods": build_methods(month),
        "metros": metros,
    }


# ---------- fetching ----------

def download(dest_dir: Path = RAW_DIR) -> Path:
    """Always re-download: the file is updated in place each month."""
    req = urllib.request.Request(URL, headers={"User-Agent": "time-to-afford/0.1"})
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
        data = resp.read()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(URL).name
    dest.write_bytes(data)
    return dest


# ---------- entry point ----------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path, help="local PET_PRI_GND_A_EPMR_PTE_DPGAL_M.xls")
    p.add_argument("--out", type=Path, default=OUT_PATH)
    args = p.parse_args(argv)

    path = args.file or download()
    month, metros = extract_latest(find_cities_sheet(path))
    # A local file keeps the date it was downloaded, not today's date.
    retrieved = dt.date.fromtimestamp(path.stat().st_mtime) if args.file else dt.date.today()
    out = build_output(metros, month, retrieved)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    ok = sum(m["price_per_gallon"]["status"] == "ok" for m in metros.values())
    print(f"Wrote {len(metros)} metros ({ok} with prices, {out['reference_period']}) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
