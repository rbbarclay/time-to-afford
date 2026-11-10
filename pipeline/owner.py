"""Owner module: Census ACS 1-year home value and owner costs by metro -> data/owner.json.

Mortgage observed values (plan docs/plans/groceries-and-mortgage.md, section 5A):
  home_value                B25077_E001  median value, owner-occupied housing units
  owner_cost_with_mortgage  B25088_E002  median selected monthly owner costs, units with a mortgage

Selected monthly owner costs bundle the mortgage payment with real estate taxes,
insurance, utilities, and fees; the method description says so.
Reads the same keyless table-based summary files as rent.py. Only metropolitan
statistical areas are kept. All values are tier "observed".

Special values are never filled in:
  negative jam values           -> null, status "missing"
  the table's top code          -> null, status "top_coded"
    B25088: 4001    = "$4,000 or more" (observed: San Francisco, San Jose in 2025)
    B25077: 2000001 = "$2,000,000 or more" (ACS convention; not observed in 2025 metro data)

Usage:
  python pipeline/owner.py                  # download latest available year
  python pipeline/owner.py --year 2025
  python pipeline/owner.py --year 2025 --value-file B25077.dat --cost-file B25088.dat --geos-file Geos.txt
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
from pathlib import Path

from rent import BASE, GEOS_URL, RAW_DIR, download, metro_names, parse_estimate, read_pipe, read_text_lines
from tiers import method_entry, tag

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "data" / "owner.json"

TABLE_URL = BASE + "/data/1YRData/acsdt1y{y}-{t}.dat"
METRO_PREFIX = "310M"

# output key -> table, estimate column, MOE column, top code, method key, label, description
MEASURES = {
    "home_value": {
        "table": "b25077", "est": "B25077_E001", "moe": "B25077_M001", "top_code": 2000001,
        "method": "acs_home_value", "label": "Median home value",
        "description": "Census ACS 1-year median value of owner-occupied housing units, for the metro",
    },
    "owner_cost_with_mortgage": {
        "table": "b25088", "est": "B25088_E002", "moe": "B25088_M002", "top_code": 4001,
        "method": "acs_owner_cost_with_mortgage", "label": "Median monthly owner costs, with a mortgage",
        "description": ("Census ACS 1-year median selected monthly owner costs for owner-occupied units with a "
                        "mortgage, for the metro. Includes the mortgage payment plus real estate taxes, "
                        "homeowner's insurance, utilities, and fees; not the mortgage payment alone"),
    },
}


def extract_metros(rows_by_measure: dict[str, list[dict]], names: dict) -> dict:
    """rows_by_measure: {measure key: parsed rows of that measure's table}."""
    metros: dict[str, dict] = {}
    for key, spec in MEASURES.items():
        rows = rows_by_measure[key]
        if rows and (missing := {spec["est"], spec["moe"], "GEO_ID"} - set(rows[0])):
            raise ValueError(f"ACS {spec['table'].upper()} is missing expected columns: {sorted(missing)}")
        for r in rows:
            gid, code = r["GEO_ID"], r["GEO_ID"][-5:]
            if not gid.startswith(METRO_PREFIX) or code not in names:
                continue
            value = parse_estimate(r.get(spec["est"]), r.get(spec["moe"]), top_code=spec["top_code"])
            metros.setdefault(code, {"name": names[code]})[key] = tag(value, "observed", spec["method"])
    # A metro absent from one table is missing there, not dropped or filled in.
    for code, entry in metros.items():
        for key, spec in MEASURES.items():
            entry.setdefault(key, tag({"value": None, "moe": None, "status": "missing"}, "observed", spec["method"]))
    return dict(sorted(metros.items()))


def build_methods(year: int) -> dict:
    return {
        spec["method"]: method_entry(
            spec["description"],
            [{"source": "census_acs", "url": TABLE_URL.format(y=year, t=spec["table"]),
              "table": spec["table"].upper(), "estimate": spec["est"], "margin_of_error": spec["moe"]}],
            str(year))
        for spec in MEASURES.values()
    }


def build_output(metros: dict, year: int, retrieved: dt.date) -> dict:
    return {
        "source": "U.S. Census Bureau, American Community Survey (ACS) 1-year estimates, tables B25077 and B25088",
        "source_url": TABLE_URL.format(y=year, t="b25088"),
        "reference_period": f"{year} (ACS 1-year)",
        "as_of": str(year),
        "retrieved": retrieved.isoformat(),
        "basis": ("Median home value and median monthly owner costs for owners with a mortgage "
                  "(owner costs include taxes, insurance, utilities, and fees), metropolitan statistical areas"),
        "attribution": "Source: U.S. Census Bureau, American Community Survey",
        "measures": {k: spec["label"] for k, spec in MEASURES.items()},
        "methods": build_methods(year),
        "metros": metros,
    }


def download_year(year: int) -> dict[str, Path]:
    paths = {k: download(TABLE_URL.format(y=year, t=s["table"]), RAW_DIR / f"acsdt1y{year}-{s['table']}.dat")
             for k, s in MEASURES.items()}
    paths["geos"] = download(GEOS_URL.format(y=year), RAW_DIR / f"Geos{year}1YR.txt")
    return paths


def download_latest(today: dt.date) -> tuple[int, dict[str, Path]]:
    errors = []
    for year in (today.year - 1, today.year - 2):
        try:
            return year, download_year(year)
        except urllib.error.HTTPError as e:
            errors.append(f"{year}: HTTP {e.code}")
    raise RuntimeError("Could not download ACS owner files (" + "; ".join(errors) + ")")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--year", type=int, help="ACS 1-year vintage (default: latest available)")
    p.add_argument("--value-file", type=Path, help="local acsdt1yYYYY-b25077.dat")
    p.add_argument("--cost-file", type=Path, help="local acsdt1yYYYY-b25088.dat")
    p.add_argument("--geos-file", type=Path, help="local GeosYYYY1YR.txt")
    p.add_argument("--out", type=Path, default=OUT_PATH)
    args = p.parse_args(argv)

    today = dt.date.today()
    local = [args.value_file, args.cost_file, args.geos_file]
    if any(local):
        if not (all(local) and args.year):
            p.error("--value-file, --cost-file, and --geos-file must be given together, with --year")
        year = args.year
        paths = {"home_value": args.value_file, "owner_cost_with_mortgage": args.cost_file, "geos": args.geos_file}
        retrieved = dt.date.fromtimestamp(args.cost_file.stat().st_mtime)  # keep the file's download date
    else:
        year, paths = (args.year, download_year(args.year)) if args.year else download_latest(today)
        retrieved = today

    names = metro_names(read_pipe(read_text_lines(paths["geos"])))
    rows = {k: read_pipe(read_text_lines(paths[k])) for k in MEASURES}
    metros = extract_metros(rows, names)

    out = build_output(metros, year, retrieved)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    counts = {k: {} for k in MEASURES}
    for m in metros.values():
        for k in MEASURES:
            counts[k][m[k]["status"]] = counts[k].get(m[k]["status"], 0) + 1
    print(f"Wrote {len(metros)} metros (ACS {year} 1-year) to {args.out}; status counts: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
