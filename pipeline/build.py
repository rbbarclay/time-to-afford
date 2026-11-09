"""Build web/data/metros.json from data/wages.json, data/rent.json, data/gas.json.

Runs validate.py first and refuses to build if validation fails.
Every value keeps its {value, status} form. Metros outside a source's
coverage get status "not_covered" (distinct from "missing" in the source).

Usage:
  python pipeline/build.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import validate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT_PATH = ROOT / "web" / "data" / "metros.json"

SOURCE_FIELDS = ("source", "source_url", "reference_period", "as_of", "basis", "attribution", "coverage_note")
NOT_COVERED = {"value": None, "status": "not_covered"}


def source_meta(doc: dict, extra: tuple[str, ...] = ()) -> dict:
    return {k: doc[k] for k in SOURCE_FIELDS + extra if k in doc}


def build_bundle(wages: dict, rent: dict, gas: dict, built: dt.date) -> dict:
    metros = []
    for code, w in wages["metros"].items():
        r = rent["metros"].get(code)
        g = gas["metros"].get(code)
        metros.append({
            "cbsa": code,
            "name": (r or {}).get("name") or w["name"],  # ACS names keep diacritics
            "wage_median": w["hourly_median"],
            "rent": {k: r[k] for k in rent["measures"]} if r else {k: NOT_COVERED for k in rent["measures"]},
            "gas": g["price_per_gallon"] if g else NOT_COVERED,
        })
    metros.sort(key=lambda m: m["name"].casefold())
    return {
        "built": built.isoformat(),
        "sources": {
            "wage": {**source_meta(wages), "measure": "hourly_median"},
            "rent": source_meta(rent, ("measures", "default_measure")),
            "gas": source_meta(gas),
        },
        "metros": metros,
    }


def main(argv=None) -> int:
    if validate.main([]) != 0:
        print("Validation failed; not building.", file=sys.stderr)
        return 1
    wages, rent, gas = (json.loads((DATA / f).read_text(encoding="utf-8"))
                        for f in ("wages.json", "rent.json", "gas.json"))
    bundle = build_bundle(wages, rent, gas, dt.date.today())
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {len(bundle['metros'])} metros to {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
