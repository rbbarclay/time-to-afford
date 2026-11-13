"""Groceries module (phase G1): national BLS average prices -> data/groceries.json.

Reads the versioned basket in pipeline/config/basket.yml and fetches each item's
BLS Average Price series (U.S. city average) for its latest month. Values are
tier "observed" with geography "US"; there are no metro values in this phase.
Each item keeps its own as-of month. A series with no value is "missing" and is
never filled in from an earlier month or another item.

Sources:
  default        BLS public data API v1 (one request; needs BLS_CONTACT or --contact)
  --file PATH    a local copy of https://download.bls.gov/pub/time.series/ap/ap.data.3.Food

Usage:
  python pipeline/groceries.py
  python pipeline/groceries.py --file data/raw/bls/ap.data.3.Food
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi
import yaml

from tiers import method_entry, tag

ROOT = Path(__file__).resolve().parents[1]
BASKET_PATH = Path(__file__).resolve().parent / "config" / "basket.yml"
OUT_PATH = ROOT / "data" / "groceries.json"

BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
FLAT_FILE_URL = "https://download.bls.gov/pub/time.series/ap/ap.data.3.Food"
SOURCE_PAGE = "https://www.bls.gov/cpi/average-price-data.htm"
SERIES_RE = re.compile(r"^APU\d{4}\d{6}$")
MONTH_RE = re.compile(r"^M(0[1-9]|1[0-2])$")  # M13 is an annual average, not a month


# ---------- basket ----------

def load_basket(path: Path = BASKET_PATH) -> dict:
    basket = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = basket.get("items") or []
    if not isinstance(basket.get("version"), int):
        raise ValueError("basket.yml: version must be an integer")
    if not items:
        raise ValueError("basket.yml: no items")
    keys = [i.get("key") for i in items]
    if len(set(keys)) != len(keys):
        raise ValueError(f"basket.yml: duplicate item keys {keys}")
    for i in items:
        missing = {"key", "label", "series", "unit", "quantity"} - set(i)
        if missing:
            raise ValueError(f"basket.yml item {i.get('key')}: missing {sorted(missing)}")
        if not SERIES_RE.match(str(i["series"])):
            raise ValueError(f"basket.yml item {i['key']}: unexpected series id {i['series']!r}")
        if not (isinstance(i["quantity"], (int, float)) and i["quantity"] > 0):
            raise ValueError(f"basket.yml item {i['key']}: quantity must be positive")
    return basket


# ---------- parsing ----------

def _value(text) -> float | None:
    try:
        v = float(str(text).strip())
    except (TypeError, ValueError):
        return None  # BLS uses "-" for unavailable
    return v if v > 0 else None


def latest_from_api(payload: dict) -> dict:
    """{series: (year, month, value|None)} for the latest monthly observation in a BLS API response."""
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API: {payload.get('status')} {payload.get('message')}")
    out = {}
    for s in payload["Results"]["series"]:
        months = [d for d in s.get("data", []) if MONTH_RE.match(d.get("period", ""))]
        if months:
            d = max(months, key=lambda d: (int(d["year"]), d["period"]))
            out[s["seriesID"]] = (int(d["year"]), int(d["period"][1:]), _value(d["value"]))
    return out


def latest_from_flat(lines, wanted: set[str]) -> dict:
    """Same result from the tab-separated ap.data flat file (header row first)."""
    out = {}
    for ln in lines:
        parts = [p.strip() for p in ln.split("\t")]
        if len(parts) < 4 or parts[0] not in wanted or not MONTH_RE.match(parts[2]):
            continue
        key = (int(parts[1]), int(parts[2][1:]))
        if parts[0] not in out or key > out[parts[0]][:2]:
            out[parts[0]] = (*key, _value(parts[3]))
    return out


def build_items(basket: dict, latest: dict, source_url: str) -> tuple[dict, dict]:
    """Returns (items, methods). Items with no observation are 'missing'."""
    items, methods = {}, {}
    for i in basket["items"]:
        method = f"bls_ap_{i['key']}"
        obs = latest.get(i["series"])
        as_of = f"{obs[0]}-{obs[1]:02d}" if obs else None
        value = {"value": obs[2], "status": "ok"} if obs and obs[2] is not None else {"value": None, "status": "missing"}
        items[i["key"]] = {"label": i["label"], "unit": i["unit"], "quantity": i["quantity"], "series": i["series"],
                           **tag(value, "observed", method)}
        methods[method] = method_entry(
            f"BLS Average Price Data, U.S. city average, {i['label'].lower()}, per {i['unit']}, not seasonally adjusted",
            [{"source": "bls_ap", "url": source_url, "series": i["series"]}],
            as_of or "unavailable")
    return items, methods


def build_output(basket: dict, items: dict, methods: dict, retrieved: dt.date, source_url: str) -> dict:
    months = sorted(m["as_of"] for m in methods.values() if m["as_of"] != "unavailable")
    latest = months[-1] if months else None
    return {
        "source": "U.S. Bureau of Labor Statistics, Average Price Data (CPI)",
        "source_url": SOURCE_PAGE,
        "geography": basket.get("geography", "US"),
        "basket_version": basket["version"],
        "reference_period": (dt.date.fromisoformat(latest + "-01").strftime("%B %Y") if latest else "unavailable"),
        "as_of": latest,
        "items_same_month": len(set(months)) == 1 and len(months) == len(items),
        "retrieved": retrieved.isoformat(),
        "basis": "National (U.S. city average) retail prices; not metro values",
        "attribution": "Source: U.S. Bureau of Labor Statistics, Average Price Data",
        "methods": methods,
        "items": items,
    }


# ---------- fetching ----------

def fetch_api(series: list[str], contact: str, today: dt.date) -> dict:
    body = json.dumps({"seriesid": series, "startyear": str(today.year - 1), "endyear": str(today.year)}).encode()
    req = urllib.request.Request(BLS_API, data=body, headers={
        "User-Agent": f"time-to-afford/0.1 (contact: {contact})", "Content-Type": "application/json"})
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
        return json.loads(resp.read())


# ---------- entry point ----------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path, help="local ap.data.3.Food flat file")
    p.add_argument("--basket", type=Path, default=BASKET_PATH)
    p.add_argument("--contact", default=os.environ.get("BLS_CONTACT"))
    p.add_argument("--out", type=Path, default=OUT_PATH)
    args = p.parse_args(argv)

    basket = load_basket(args.basket)
    series = [i["series"] for i in basket["items"]]
    today = dt.date.today()
    if args.file:
        latest = latest_from_flat(args.file.read_text(encoding="utf-8").splitlines(), set(series))
        source_url, retrieved = FLAT_FILE_URL, dt.date.fromtimestamp(args.file.stat().st_mtime)
    else:
        if not args.contact:
            p.error("the BLS API needs --contact or BLS_CONTACT (or use --file)")
        latest = latest_from_api(fetch_api(series, args.contact, today))
        source_url, retrieved = BLS_API, today

    items, methods = build_items(basket, latest, source_url)
    out = build_output(basket, items, methods, retrieved, source_url)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    ok = sum(i["status"] == "ok" for i in items.values())
    print(f"Wrote {ok}/{len(items)} basket items ({out['reference_period']}, basket v{basket['version']}) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
