"""Rent module: Census ACS 1-year median gross rent by metro -> data/rent.json.

Uses the ACS table-based summary files (no API key needed):
  table B25031 (median gross rent by bedrooms) + the Geos file for area names.
Only metropolitan statistical areas are kept (micropolitan areas dropped).

Special values are never imputed:
  negative jam values (e.g. -666666666, sample too small) -> null, status "missing"
  3501 ("$3,500+" top code)                              -> null, status "top_coded"

Usage:
  python pipeline/rent.py                       # download latest available year
  python pipeline/rent.py --year 2025
  python pipeline/rent.py --file B25031.dat --geos-file Geos.txt --year 2025
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import certifi

from tiers import method_entry, tag

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "acs"
OUT_PATH = ROOT / "data" / "rent.json"

BASE = "https://www2.census.gov/programs-surveys/acs/summary_file/{y}/table-based-SF"
DATA_URL = BASE + "/data/1YRData/acsdt1y{y}-b25031.dat"
GEOS_URL = BASE + "/documentation/Geos{y}1YR.txt"

METRO_PREFIX = "310M"          # summary level 310 = metro/micro statistical area
METRO_SUFFIX = " Metro Area"   # distinguishes metro from micro in the Geos NAME
TOP_CODE = 3501                # ACS code for "$3,500+"

# output key -> (estimate column, margin-of-error column, label)
MEASURES = {
    "all_units": ("B25031_E001", "B25031_M001", "All units"),
    "one_bedroom": ("B25031_E003", "B25031_M003", "1 bedroom"),
    "two_bedroom": ("B25031_E004", "B25031_M004", "2 bedrooms"),
}
DEFAULT_MEASURE = "all_units"
METHOD_KEYS = {"all_units": "acs_rent_all_units", "one_bedroom": "acs_rent_1br", "two_bedroom": "acs_rent_2br"}


# ---------- parsing ----------

def _to_int(raw: str | None):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def parse_estimate(est: str | None, moe: str | None) -> dict:
    """Convert an ACS estimate/MOE pair into {"value", "moe", "status"}."""
    e, m = _to_int(est), _to_int(moe)
    moe_val = m if m is not None and m >= 0 else None
    if e is None or e < 0:
        return {"value": None, "moe": None, "status": "missing"}
    if e == TOP_CODE:
        return {"value": None, "moe": None, "status": "top_coded"}
    return {"value": e, "moe": moe_val, "status": "ok"}


def read_pipe(lines) -> list[dict]:
    """Parse pipe-delimited text (header row first) into dicts."""
    it = iter(lines)
    header = next(it).rstrip("\r\n").split("|")
    return [dict(zip(header, ln.rstrip("\r\n").split("|"))) for ln in it if ln.strip()]


def read_text_lines(path: Path) -> list[str]:
    """Census files are UTF-8; fall back to Latin-1 for older vintages."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return raw.decode("latin-1").splitlines()


def metro_names(geo_rows: list[dict]) -> dict:
    """{cbsa: name} for metropolitan (not micropolitan) areas."""
    out = {}
    for r in geo_rows:
        gid, name = r.get("GEO_ID", ""), r.get("NAME", "")
        if gid.startswith(METRO_PREFIX) and name.endswith(METRO_SUFFIX):
            out[gid[-5:]] = name[: -len(METRO_SUFFIX)]
    return out


def extract_metros(data_rows: list[dict], names: dict) -> dict:
    needed = {c for est, moe, _ in MEASURES.values() for c in (est, moe)} | {"GEO_ID"}
    if data_rows and (missing := needed - set(data_rows[0])):
        raise ValueError(f"ACS file is missing expected columns: {sorted(missing)}")
    metros = {}
    for r in data_rows:
        gid = r["GEO_ID"]
        code = gid[-5:]
        if not gid.startswith(METRO_PREFIX) or code not in names:
            continue
        entry = {"name": names[code]}
        for key, (est, moe, _) in MEASURES.items():
            entry[key] = tag(parse_estimate(r.get(est), r.get(moe)), "observed", METHOD_KEYS[key])
        metros[code] = entry
    return dict(sorted(metros.items()))


def build_methods(year: int) -> dict:
    return {
        METHOD_KEYS[key]: method_entry(
            f"Census ACS 1-year median monthly gross rent (rent plus utilities), {label.lower()}, for the metro",
            [{"source": "census_acs", "url": DATA_URL.format(y=year), "table": "B25031",
              "estimate": est, "margin_of_error": moe}],
            str(year))
        for key, (est, moe, label) in MEASURES.items()
    }


def build_output(metros: dict, year: int, retrieved: dt.date) -> dict:
    return {
        "source": "U.S. Census Bureau, American Community Survey (ACS) 1-year estimates, table B25031",
        "source_url": DATA_URL.format(y=year),
        "reference_period": f"{year} (ACS 1-year)",
        "as_of": str(year),
        "retrieved": retrieved.isoformat(),
        "basis": "Median monthly gross rent (contract rent plus utilities), metropolitan statistical areas",
        "attribution": "Source: U.S. Census Bureau, American Community Survey",
        "measures": {k: label for k, (_, _, label) in MEASURES.items()},
        "default_measure": DEFAULT_MEASURE,
        "methods": build_methods(year),
        "metros": metros,
    }


# ---------- fetching ----------

def download(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": "time-to-afford/0.1"})
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def download_year(year: int) -> tuple[Path, Path]:
    data = download(DATA_URL.format(y=year), RAW_DIR / f"acsdt1y{year}-b25031.dat")
    geos = download(GEOS_URL.format(y=year), RAW_DIR / f"Geos{year}1YR.txt")
    return data, geos


def download_latest(today: dt.date) -> tuple[int, Path, Path]:
    """1-year estimates publish each September for the prior year."""
    errors = []
    for year in (today.year - 1, today.year - 2):
        try:
            return (year, *download_year(year))
        except urllib.error.HTTPError as e:
            errors.append(f"{year}: HTTP {e.code}")
    raise RuntimeError("Could not download ACS files (" + "; ".join(errors) + ")")


# ---------- entry point ----------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--year", type=int, help="ACS 1-year vintage (default: latest available)")
    p.add_argument("--file", type=Path, help="local acsdt1yYYYY-b25031.dat (requires --geos-file and --year)")
    p.add_argument("--geos-file", type=Path, help="local GeosYYYY1YR.txt")
    p.add_argument("--out", type=Path, default=OUT_PATH)
    args = p.parse_args(argv)

    today = dt.date.today()
    if args.file or args.geos_file:
        if not (args.file and args.geos_file and args.year):
            p.error("--file requires --geos-file and --year")
        year, data_path, geos_path = args.year, args.file, args.geos_file
    elif args.year:
        year = args.year
        data_path, geos_path = download_year(year)
    else:
        year, data_path, geos_path = download_latest(today)

    names = metro_names(read_pipe(read_text_lines(geos_path)))
    metros = extract_metros(read_pipe(read_text_lines(data_path)), names)

    # A local file keeps the date it was downloaded, not today's date.
    retrieved = dt.date.fromtimestamp(data_path.stat().st_mtime) if args.file else today
    out = build_output(metros, year, retrieved)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    counts = {k: {} for k in MEASURES}
    for m in metros.values():
        for k in MEASURES:
            s = m[k]["status"]
            counts[k][s] = counts[k].get(s, 0) + 1
    print(f"Wrote {len(metros)} metros (ACS {year} 1-year) to {args.out}; status counts: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
