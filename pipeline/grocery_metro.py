"""Metro grocery estimates (phase G2): national BLS prices x BEA goods RPP -> data/grocery_metro.json.

    estimate = national price (data/groceries.json) x metro all-goods RPP / 100

These are tier "estimated". BEA publishes no food-specific Regional Price
Parity, so the all-goods line (line 2: apparel, food, medical, recreation,
transportation, and other goods) stands in for grocery prices. Each method
string says so. The RPP itself is stored beside the estimates as an observed value.

Only metros with a BEA RPP are written (387 of 393; none of the Puerto Rico
metros have RPPs). The site build marks the rest "not_covered". A national
price that is missing gives a missing estimate; nothing is filled in.

Usage:
  python pipeline/grocery_metro.py                 # download BEA MARPP.zip (cached in data/raw/bea/)
  python pipeline/grocery_metro.py --file PATH     # local MARPP.zip
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import ssl
import sys
import urllib.request
import zipfile
from pathlib import Path

import certifi

from tiers import method_entry, tag

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW_DIR = DATA / "raw" / "bea"
OUT_PATH = DATA / "grocery_metro.json"

BEA_ZIP_URL = "https://apps.bea.gov/regional/zip/MARPP.zip"
BEA_PAGE = "https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area"
GOODS_LINE = "2"
GOODS_DESCRIPTION = "RPPs: Goods"
RPP_METHOD = "bea_rpp_goods"


# ---------- BEA RPP ----------

def read_rpp_csv(path: Path) -> tuple[str, list[dict]]:
    """Return (csv member name, rows) from MARPP.zip."""
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.startswith("MARPP_MSA") and n.endswith(".csv")]
        if not names:
            raise ValueError(f"No MARPP_MSA_*.csv in {path.name}")
        text = zf.read(names[0]).decode("latin-1")
    return names[0], list(csv.DictReader(io.StringIO(text)))


def goods_rpp(rows: list[dict], year: int | None = None) -> tuple[int, dict]:
    """Return (year, {cbsa: (name, rpp|None)}) for the goods line, latest year by default."""
    years = sorted(int(k) for k in (rows[0] if rows else {}) if k and k.strip().isdigit())
    if not years:
        raise ValueError("RPP file has no year columns")
    year = year or years[-1]
    out = {}
    for r in rows:
        if (r.get("LineCode") or "").strip() != GOODS_LINE:
            continue
        if (r.get("Description") or "").strip() != GOODS_DESCRIPTION:
            raise ValueError(f"line {GOODS_LINE} is {r.get('Description')!r}, expected {GOODS_DESCRIPTION!r}")
        code = (r.get("GeoFIPS") or "").strip().strip('"').strip()
        if len(code) != 5 or code in ("00000", "00999"):  # U.S. total and nonmetropolitan portion
            continue
        name = (r.get("GeoName") or "").replace("(Metropolitan Statistical Area)", "").replace("*", "")
        name = name.replace("Metropolitan Statistical Area", "").strip()
        try:
            value = float(str(r.get(str(year), "")).strip())
        except ValueError:
            value = None  # "(NA)" not available
        out[code] = (name, value)
    return year, out


# ---------- estimates ----------

def item_method(key: str) -> str:
    return f"est_rpp_goods_{key}"


def build(groceries: dict, rpp_year: int, rpp: dict, rpp_url: str) -> tuple[dict, dict]:
    """Returns (metros, methods)."""
    items = groceries["items"]
    methods = {
        RPP_METHOD: method_entry(
            "BEA Regional Price Parity for all goods (U.S. = 100), for the metro",
            [{"source": "bea_rpp", "url": rpp_url, "table": "MARPP", "line": GOODS_LINE, "year": rpp_year}],
            str(rpp_year)),
    }
    for key, item in items.items():
        national_as_of = groceries["methods"][item["method"]]["as_of"]
        methods[item_method(key)] = method_entry(
            (f"Estimate: national BLS average price for {item['label'].lower()} (U.S. city average, {national_as_of}) "
             f"x BEA all-goods Regional Price Parity for the metro ({rpp_year}) / 100. BEA publishes no "
             f"food-specific RPP, so the all-goods RPP is an approximation for grocery prices"),
            [{"source": "bls_ap", "series": item["series"], "as_of": national_as_of},
             {"source": "bea_rpp", "url": rpp_url, "table": "MARPP", "line": GOODS_LINE, "year": rpp_year}],
            national_as_of)

    metros = {}
    for code, (name, index) in sorted(rpp.items()):
        rpp_value = tag({"value": index, "status": "ok"} if index is not None else {"value": None, "status": "missing"},
                        "observed", RPP_METHOD)
        estimates = {}
        for key, item in items.items():
            if index is None or item["status"] != "ok":
                est = {"value": None, "status": "missing"}
            else:
                est = {"value": round(item["value"] * index / 100, 3), "status": "ok"}
            estimates[key] = tag(est, "estimated", item_method(key))
        metros[code] = {"name": name, "rpp_goods": rpp_value, "items": estimates}
    return metros, methods


def consistency(metros: dict, groceries: dict, weights: dict) -> dict:
    """Employment-weighted mean of each metro estimate, as a ratio to the national price.

    RPPs average to 100 across the whole U.S., so across metros the weighted ratio
    should sit close to 1 (slightly above, since rural areas are excluded).
    """
    out = {}
    for key, item in groceries["items"].items():
        num = den = 0.0
        for code, m in metros.items():
            est, w = m["items"][key], weights.get(code)
            if est["status"] == "ok" and w:
                num += est["value"] * w
                den += w
        out[key] = round(num / den / item["value"], 4) if den and item["status"] == "ok" else None
    return out


def build_output(metros: dict, methods: dict, groceries: dict, rpp_year: int, retrieved: dt.date) -> dict:
    return {
        "source": ("Estimates from U.S. Bureau of Labor Statistics Average Price Data and U.S. Bureau of "
                   "Economic Analysis Regional Price Parities"),
        "source_url": BEA_PAGE,
        "reference_period": f"{groceries['reference_period']} national prices; {rpp_year} price parities",
        "as_of": groceries["as_of"],
        "rpp_year": rpp_year,
        "basket_version": groceries["basket_version"],
        "retrieved": retrieved.isoformat(),
        "basis": ("Estimated metro prices: national BLS average price x BEA all-goods RPP / 100. "
                  "Not observed metro prices."),
        "coverage_note": "BEA publishes no Regional Price Parities for Puerto Rico metros; they have no estimate.",
        "attribution": ("Sources: U.S. Bureau of Labor Statistics, Average Price Data; "
                        "U.S. Bureau of Economic Analysis, Regional Price Parities"),
        "methods": methods,
        "metros": metros,
    }


def download(dest_dir: Path = RAW_DIR) -> Path:
    dest = dest_dir / "MARPP.zip"
    req = urllib.request.Request(BEA_ZIP_URL, headers={"User-Agent": "time-to-afford/0.1"})
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
        data = resp.read()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path, help="local MARPP.zip")
    p.add_argument("--year", type=int, help="RPP year (default: latest in the file)")
    p.add_argument("--out", type=Path, default=OUT_PATH)
    args = p.parse_args(argv)

    groceries = json.loads((DATA / "groceries.json").read_text(encoding="utf-8"))
    path = args.file or download()
    retrieved = dt.date.fromtimestamp(path.stat().st_mtime) if args.file else dt.date.today()
    _, rows = read_rpp_csv(path)
    rpp_year, rpp = goods_rpp(rows, args.year)

    metros, methods = build(groceries, rpp_year, rpp, BEA_ZIP_URL)
    out = build_output(metros, methods, groceries, rpp_year, retrieved)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    wages = json.loads((DATA / "wages.json").read_text(encoding="utf-8"))
    weights = {c: m["employment"]["value"] for c, m in wages["metros"].items() if m["employment"]["status"] == "ok"}
    ratio = consistency(metros, groceries, weights)
    missing = sum(m["rpp_goods"]["status"] != "ok" for m in metros.values())
    print(f"Wrote {len(metros)} metros (RPP {rpp_year}, prices {groceries['as_of']}) to {args.out}; "
          f"metros without RPP value: {missing}")
    print(f"Employment-weighted estimate / national price: {ratio}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
