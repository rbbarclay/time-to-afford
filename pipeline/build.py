"""Build web/data/metros.json from data/wages.json, rent.json, gas.json, and (if present)
owner.json, groceries.json, grocery_metro.json and metro_points.json (map positions from geo.py).

Runs validate.py first and refuses to build if validation fails.
Every value keeps its {value, status, tier, method} form, and the bundle's
`methods` table holds each method's description, inputs, and as-of date.
Metros outside a source's coverage get status "not_covered" (distinct from
"missing" in the source) and carry no tier or method, since no source reported them.
The finished bundle is checked again before it is written.

Groceries: each metro gets the estimated item prices from grocery_metro.json
(tier "estimated"); the top-level `basket` holds the national observed prices
and the quantities. Metros with no RPP (Puerto Rico) are "not_covered".

Usage:
  python pipeline/build.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import tiers
import validate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT_PATH = ROOT / "web" / "data" / "metros.json"

SOURCE_FIELDS = ("source", "source_url", "reference_period", "as_of", "basis", "attribution", "coverage_note")
NOT_COVERED = {"value": None, "status": "not_covered"}


def source_meta(doc: dict, extra: tuple[str, ...] = ()) -> dict:
    return {k: doc[k] for k in SOURCE_FIELDS + extra if k in doc}


def metro_values(m: dict):
    """(name, value) for every tagged-or-not_covered value in a bundle metro."""
    yield "wage_median", m["wage_median"]
    yield "gas", m["gas"]
    for k, v in m["rent"].items():
        yield f"rent.{k}", v
    for k, v in (m.get("owner") or {}).items():
        yield f"owner.{k}", v
    if "rpp_goods" in m:
        yield "rpp_goods", m["rpp_goods"]
    for k, v in (m.get("groceries") or {}).items():
        yield f"groceries.{k}", v


def basket_values(basket: dict | None):
    for k, item in ((basket or {}).get("items") or {}).items():
        yield f"basket.{k}.national", item["national"]


def used_methods(metros: list[dict], *docs: dict, basket: dict | None = None) -> dict:
    """Collect the methods referenced by values in the bundle (and only those)."""
    available = {k: v for d in docs if d for k, v in (d.get("methods") or {}).items()}
    used = set()
    values = [v for m in metros for _, v in metro_values(m)] + [v for _, v in basket_values(basket)]
    for v in values:
        if v.get("method"):
            used.add(v["method"])
    missing = used - set(available)
    if missing:
        raise ValueError(f"values reference undefined methods: {sorted(missing)}")
    return {k: available[k] for k in sorted(used)}


def check_bundle(bundle: dict) -> list[str]:
    errors = tiers.check_methods("bundle", bundle.get("methods"))
    methods = bundle.get("methods") or {}
    for m in bundle["metros"]:
        for name, v in metro_values(m):
            errors += tiers.check_value(f"bundle {m['cbsa']}.{name}", v, methods,
                                        allow_untagged_status=("not_covered",))
        for name, v in (m.get("groceries") or {}).items():
            if v["status"] != "not_covered" and v.get("tier") != "estimated":
                errors.append(f"bundle {m['cbsa']}.groceries.{name}: tier {v.get('tier')}, expected estimated")
    for name, v in basket_values(bundle.get("basket")):
        errors += tiers.check_value(f"bundle {name}", v, methods)
    return errors


def build_basket(groceries: dict) -> dict:
    """National observed prices plus quantities: the inputs the front end needs for the basket scenario."""
    return {
        "version": groceries["basket_version"],
        "as_of": groceries["as_of"],
        "items": {k: {"label": i["label"], "unit": i["unit"], "quantity": i["quantity"],
                      "national": {f: i[f] for f in ("value", "status", "tier", "method")}}
                  for k, i in groceries["items"].items()},
    }


def build_bundle(wages: dict, rent: dict, gas: dict, built: dt.date, owner: dict | None = None,
                 groceries: dict | None = None, grocery_metro: dict | None = None,
                 points: dict | None = None) -> dict:
    if (groceries is None) != (grocery_metro is None):
        raise ValueError("groceries.json and grocery_metro.json must be included together")
    if groceries is not None and grocery_metro.get("as_of") != groceries.get("as_of"):
        raise ValueError("grocery_metro.json was built from a different national month; rerun grocery_metro.py")
    metros = []
    for code, w in wages["metros"].items():
        r = rent["metros"].get(code)
        g = gas["metros"].get(code)
        m = {
            "cbsa": code,
            "name": (r or {}).get("name") or w["name"],  # ACS names keep diacritics
            "wage_median": w["hourly_median"],
            "rent": {k: r[k] for k in rent["measures"]} if r else {k: NOT_COVERED for k in rent["measures"]},
            "gas": g["price_per_gallon"] if g else NOT_COVERED,
        }
        if owner is not None:
            o = owner["metros"].get(code)
            m["owner"] = {k: o[k] if o else NOT_COVERED for k in owner["measures"]}
        if grocery_metro is not None:
            e = grocery_metro["metros"].get(code)
            m["rpp_goods"] = e["rpp_goods"] if e else NOT_COVERED
            m["groceries"] = {k: e["items"][k] if e else NOT_COVERED for k in groceries["items"]}
        if points is not None:
            if code not in points["points"]:
                raise ValueError(f"metro {code} has no map point; rerun geo.py")
            m["xy"] = points["points"][code]["xy"]
        metros.append(m)
    metros.sort(key=lambda m: m["name"].casefold())
    sources = {
        "wage": {**source_meta(wages), "measure": "hourly_median"},
        "rent": source_meta(rent, ("measures", "default_measure")),
        "gas": source_meta(gas),
    }
    basket = None
    if owner is not None:
        sources["owner"] = source_meta(owner, ("measures",))
    if groceries is not None:
        sources["groceries"] = source_meta(groceries)
        sources["grocery_estimates"] = source_meta(grocery_metro, ("rpp_year",))
        basket = build_basket(groceries)
    bundle = {
        "built": built.isoformat(),
        "sources": sources,
        "methods": used_methods(metros, wages, rent, gas, owner, groceries, grocery_metro, basket=basket),
        "metros": metros,
    }
    if points is not None:
        sources["map"] = {"source": points["source"], "source_url": points["source_url"],
                          "width": points["width"], "height": points["height"]}
    if basket is not None:
        bundle["basket"] = basket
    return bundle


def main(argv=None) -> int:
    if validate.main([]) != 0:
        print("Validation failed; not building.", file=sys.stderr)
        return 1
    load = lambda f: json.loads((DATA / f).read_text(encoding="utf-8")) if (DATA / f).exists() else None
    wages, rent, gas = load("wages.json"), load("rent.json"), load("gas.json")
    bundle = build_bundle(wages, rent, gas, dt.date.today(), owner=load("owner.json"),
                          groceries=load("groceries.json"), grocery_metro=load("grocery_metro.json"),
                          points=load("metro_points.json"))
    if errors := check_bundle(bundle):
        for e in errors:
            print("ERROR", e, file=sys.stderr)
        print("Bundle check failed; not building.", file=sys.stderr)
        return 1
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {len(bundle['metros'])} metros to {OUT_PATH} ({OUT_PATH.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
