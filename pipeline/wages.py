"""Wage module: BLS OEWS metro-area wages -> data/wages.json.

Keeps the "All Occupations" (00-0000) row for each metropolitan statistical
area. BLS special codes are never imputed:
  "*", "**", "~", blank -> value null, status "missing"
  "#" (at or above the BLS top-code cap) -> value null, status "top_coded"

Usage:
  python pipeline/wages.py                 # download latest release (needs BLS_CONTACT or --contact)
  python pipeline/wages.py --file PATH     # use an already-downloaded oesmYYma.zip or .xlsx
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import certifi
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_PATH = ROOT / "data" / "wages.json"

URL_TEMPLATE = "https://www.bls.gov/oes/special-requests/oesm{yy}ma.zip"
SOURCE_PAGE = "https://www.bls.gov/oes/tables.htm"

ALL_OCCUPATIONS = "00-0000"
AREA_TYPE_MSA = 4  # OEWS area type 4 = metropolitan statistical area
FIELDS = {"H_MEDIAN": "hourly_median", "H_MEAN": "hourly_mean", "TOT_EMP": "employment"}


# ---------- parsing ----------

def parse_value(raw) -> dict:
    """Convert one OEWS cell into {"value": float|None, "status": str}."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return {"value": None, "status": "missing"}
    if isinstance(raw, (int, float)):
        return {"value": float(raw), "status": "ok"}
    text = str(raw).strip()
    if text == "#":
        return {"value": None, "status": "top_coded"}
    if text in {"", "*", "**", "~"}:
        return {"value": None, "status": "missing"}
    try:
        return {"value": float(text.replace(",", "")), "status": "ok"}
    except ValueError:
        return {"value": None, "status": "missing"}


def extract_metros(df: pd.DataFrame) -> dict:
    """Return {cbsa_code: {...}} for all-occupations rows of MSAs."""
    df = df.rename(columns=str.upper)
    occ_col = "OCC_CODE" if "OCC_CODE" in df.columns else "O_CODE"
    required = {"AREA", "AREA_TITLE", "AREA_TYPE", occ_col, *FIELDS}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"OEWS file is missing expected columns: {sorted(missing)}")

    rows = df[
        (df[occ_col].astype(str).str.strip() == ALL_OCCUPATIONS)
        & (pd.to_numeric(df["AREA_TYPE"], errors="coerce") == AREA_TYPE_MSA)
    ]
    metros = {}
    for _, row in rows.iterrows():
        code = str(row["AREA"]).strip().split(".")[0].zfill(5)
        entry = {"name": str(row["AREA_TITLE"]).strip()}
        for src, dst in FIELDS.items():
            entry[dst] = parse_value(row[src])
        metros[code] = entry
    return dict(sorted(metros.items()))


def read_oews(path: Path) -> pd.DataFrame:
    """Read the metro Excel sheet from an oesmYYma.zip or a bare .xlsx."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if re.search(r"MSA_M\d{4}_dl\.xlsx$", n, re.I)]
            if not names:
                raise ValueError(f"No MSA_M*_dl.xlsx found in {path.name}")
            return pd.read_excel(io.BytesIO(zf.read(names[0])), dtype=object)
    return pd.read_excel(path, dtype=object)


def year_from_name(path: Path) -> int:
    m = re.search(r"oesm(\d{2})ma", path.name, re.I) or re.search(r"MSA_M(\d{4})", path.name, re.I)
    if not m:
        raise ValueError(f"Cannot infer OEWS year from file name: {path.name}")
    y = int(m.group(1))
    return y + 2000 if y < 100 else y


def build_output(metros: dict, year: int, retrieved: dt.date, source_url: str) -> dict:
    return {
        "source": "U.S. Bureau of Labor Statistics, Occupational Employment and Wage Statistics (OEWS)",
        "source_url": source_url,
        "reference_period": f"May {year}",
        "as_of": f"{year}-05",
        "retrieved": retrieved.isoformat(),
        "basis": "Pre-tax hourly wage, all occupations, metropolitan statistical areas",
        "attribution": "Source: U.S. Bureau of Labor Statistics, OEWS",
        "metros": metros,
    }


# ---------- fetching ----------

def download(year: int, contact: str, dest_dir: Path = RAW_DIR) -> Path:
    """Download oesmYYma.zip into data/raw/ (skipped if already present)."""
    yy = f"{year % 100:02d}"
    dest = dest_dir / f"oesm{yy}ma.zip"
    if dest.exists():
        return dest
    req = urllib.request.Request(
        URL_TEMPLATE.format(yy=yy),
        # BLS rejects User-Agents containing a URL; project name + contact is accepted.
        headers={"User-Agent": f"time-to-afford/0.1 (contact: {contact})"},
    )
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
        data = resp.read()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def download_latest(contact: str, today: dt.date) -> Path:
    """Try the most recent plausible release first (May data publishes the following spring)."""
    errors = []
    for year in (today.year - 1, today.year - 2):
        try:
            return download(year, contact)
        except urllib.error.HTTPError as e:
            errors.append(f"{year}: HTTP {e.code}")
    raise RuntimeError("Could not download OEWS metro file (" + "; ".join(errors) + ")")


# ---------- entry point ----------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path, help="local oesmYYma.zip or MSA_MYYYY_dl.xlsx")
    p.add_argument("--contact", default=os.environ.get("BLS_CONTACT"),
                   help="contact email for the BLS User-Agent (default: $BLS_CONTACT)")
    p.add_argument("--out", type=Path, default=OUT_PATH)
    args = p.parse_args(argv)

    today = dt.date.today()
    if args.file:
        path = args.file
    else:
        if not args.contact:
            p.error("downloading requires --contact or BLS_CONTACT (or use --file)")
        path = download_latest(args.contact, today)

    year = year_from_name(path)
    metros = extract_metros(read_oews(path))
    out = build_output(metros, year, today, URL_TEMPLATE.format(yy=f"{year % 100:02d}"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n")

    statuses = {}
    for m in metros.values():
        s = m["hourly_median"]["status"]
        statuses[s] = statuses.get(s, 0) + 1
    print(f"Wrote {len(metros)} metros (May {year}) to {args.out}; median status counts: {statuses}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
