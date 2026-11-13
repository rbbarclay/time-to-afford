"""Validate data/wages.json, data/rent.json, data/gas.json across all metros.

Files: data/wages.json, rent.json, gas.json, plus owner.json (ACS home value and
owner costs), groceries.json (national BLS average prices), and grocery_metro.json
(estimated metro prices: national price x BEA goods RPP / 100), if present.

Checks
  1. structure    every value is {value, status, tier, method}; null iff status != "ok";
                  every method key is defined in the file's methods table, and every
                  method has a description, inputs, and as_of; files carry as_of
  2. alignment    rent metros == wage metros; gas metros are a subset of wage metros
  3. ranges       plausible bounds (out-of-range is a WARNING for human review, never changed)
  4. references   values match independently published figures, stored in
                  pipeline/reference/references.json:
                    wages -> BLS public API v1 (OEWS hourly median series)
                    rent  -> Census ACS table B25064 (median gross rent, should equal B25031 all units)
                    gas   -> EIA HTML table (same series as the spreadsheet)
                    owner -> Census ACS table B25097 total (median value), which should
                             equal B25077. Census publishes no second median for owner
                             costs (B25088) in these files, so owner costs get structure
                             and range checks only.
                    groceries -> BLS ap.data.3.Food flat file (a separate BLS
                             publication from the API used to build the data)
  5. grocery estimates  grocery_metro.json metros are wage metros; each estimate equals
                  national price x RPP / 100 recomputed from groceries.json (same month);
                  RPP range and employment-weighted mean near national are WARNINGS

Writes data/validation_report.csv: one row per metro with inputs, as-of dates,
hours of work (rent / median wage, gas per gallon / median wage), and the
measures that are missing.

Usage:
  python pipeline/validate.py                         # validate using stored references
  python pipeline/validate.py --refresh-references    # re-fetch all references (BLS_CONTACT or --contact required)
  python pipeline/validate.py --refresh-references owner   # re-fetch only some: wage, rent, gas, owner, groceries
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from pathlib import Path

import certifi

import tiers

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REF_PATH = Path(__file__).resolve().parent / "reference" / "references.json"
REPORT_PATH = DATA / "validation_report.csv"

RANGES = {"wage": (8.0, 100.0), "rent": (300, 5000), "gas": (2.0, 9.0),
          "home_value": (50_000, 3_000_000), "owner_cost": (500, 6000), "grocery_item": (0.10, 30.0),
          "rpp_goods": (80.0, 125.0), "grocery_metro_ratio": (0.97, 1.03)}
RENT_KEYS = ("all_units", "one_bedroom", "two_bedroom")
OWNER_KEYS = ("home_value", "owner_cost_with_mortgage")
REFERENCE_SOURCES = ("wage", "rent", "gas", "owner", "groceries")
BLS_AP_FLAT = "https://download.bls.gov/pub/time.series/ap/ap.data.3.Food"

BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_BATCH = 25  # API v1 limit: 25 series per request, 25 requests per day
CENSUS_TABLE = ("https://www2.census.gov/programs-surveys/acs/summary_file/{y}/table-based-SF/"
                "data/1YRData/acsdt1y{y}-{t}.dat")
EIA_HTML = "https://www.eia.gov/dnav/pet/pet_pri_gnd_a_epmr_pte_dpgal_m.htm"
EIA_CITY_LABELS = ["Boston", "Chicago", "Cleveland", "Denver", "Houston", "Los Angeles", "Miami",
                   "New York City", "San Francisco", "Seattle"]


# ---------- loading ----------

def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def value_of(field: dict | None):
    return field["value"] if field and field.get("status") == "ok" else None


# ---------- checks ----------

def check_structure(label: str, doc: dict, fields: list[str]) -> list[str]:
    errors = []
    if not doc.get("as_of"):
        errors.append(f"{label}: missing as_of")
    methods = doc.get("methods") or {}
    errors += tiers.check_methods(label, doc.get("methods"))
    for code, m in doc.get("metros", {}).items():
        if not re.fullmatch(r"\d{5}", code):
            errors.append(f"{label} {code}: code is not a 5-digit CBSA")
        for f in fields:
            v = m.get(f)
            if not isinstance(v, dict) or "status" not in v or "value" not in v:
                errors.append(f"{label} {code}.{f}: not a {{value, status}} object")
            else:
                if (v["value"] is None) != (v["status"] != "ok"):
                    errors.append(f"{label} {code}.{f}: value/status mismatch {v}")
                errors += tiers.check_value(f"{label} {code}.{f}", v, methods)
    return errors


def check_national(label: str, doc: dict) -> list[str]:
    """Structure checks for a national file with an `items` table instead of `metros`."""
    errors = [] if doc.get("as_of") else [f"{label}: missing as_of"]
    methods = doc.get("methods") or {}
    errors += tiers.check_methods(label, doc.get("methods"))
    if not doc.get("items"):
        errors.append(f"{label}: no items")
    for key, v in (doc.get("items") or {}).items():
        if not isinstance(v, dict) or "status" not in v or "value" not in v:
            errors.append(f"{label} {key}: not a {{value, status}} object")
            continue
        if (v["value"] is None) != (v["status"] != "ok"):
            errors.append(f"{label} {key}: value/status mismatch")
        errors += tiers.check_value(f"{label} {key}", v, methods)
    return errors


def check_grocery_ranges(groceries: dict) -> list[str]:
    lo, hi = RANGES["grocery_item"]
    return [f"groceries {k}={value_of(v)} outside [{lo}, {hi}]" for k, v in groceries["items"].items()
            if value_of(v) is not None and not lo <= value_of(v) <= hi]


def check_grocery_metro(gm: dict, groceries: dict, wages: dict) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings) for the estimated metro grocery prices."""
    errors = [] if gm.get("as_of") else ["grocery_metro: missing as_of"]
    methods = gm.get("methods") or {}
    errors += tiers.check_methods("grocery_metro", methods)
    if gm.get("as_of") != groceries.get("as_of"):
        errors.append(f"grocery_metro: national month {gm.get('as_of')} but groceries.json is "
                      f"{groceries.get('as_of')} (rerun grocery_metro.py)")
    extra = set(gm["metros"]) - set(wages["metros"])
    if extra:
        errors.append(f"grocery_metro: metros not in wages: {sorted(extra)}")
    warnings = []
    lo, hi = RANGES["rpp_goods"]
    num, den = {}, {}
    for code, m in gm["metros"].items():
        rpp = m["rpp_goods"]
        errors += tiers.check_value(f"grocery_metro {code}.rpp_goods", rpp, methods)
        if value_of(rpp) is not None and not lo <= rpp["value"] <= hi:
            warnings.append(f"grocery_metro {code} rpp_goods={rpp['value']} outside [{lo}, {hi}]")
        if set(m["items"]) != set(groceries["items"]):
            errors.append(f"grocery_metro {code}: items differ from groceries.json")
            continue
        for key, est in m["items"].items():
            where = f"grocery_metro {code}.{key}"
            errors += tiers.check_value(where, est, methods)
            if est.get("tier") != "estimated":
                errors.append(f"{where}: tier {est.get('tier')}, expected estimated")
            national = value_of(groceries["items"][key])
            expected = (round(national * rpp["value"] / 100, 3)
                        if national is not None and value_of(rpp) is not None else None)
            if value_of(est) != expected:
                errors.append(f"{where}: {value_of(est)} != national x RPP / 100 = {expected}")
            w = value_of(wages["metros"].get(code, {}).get("employment"))
            if expected is not None and w:
                num[key] = num.get(key, 0) + expected * w
                den[key] = den.get(key, 0) + w
    lo, hi = RANGES["grocery_metro_ratio"]
    for key in num:
        ratio = num[key] / den[key] / value_of(groceries["items"][key])
        if not lo <= ratio <= hi:
            warnings.append(f"grocery_metro {key}: employment-weighted mean / national = {ratio:.4f} "
                            f"outside [{lo}, {hi}]")
    return errors, warnings


def check_grocery_reference(groceries: dict, refs: dict) -> tuple[list[str], int]:
    """Each item must match the BLS flat file for the same series and month. Returns (errors, items checked)."""
    ref = refs.get("bls_ap_flat")
    if not ref:
        return ["groceries: no reference data (bls_ap_flat); run with --refresh-references groceries"], 0
    errors, checked = [], 0
    for key, item in groceries["items"].items():
        r = ref["values"].get(item["series"])
        if r is None:
            errors.append(f"groceries {key}: series {item['series']} not in reference")
            continue
        as_of = groceries["methods"][item["method"]]["as_of"]
        checked += 1
        if r["as_of"] != as_of:
            errors.append(f"groceries {key}: month {as_of} but reference has {r['as_of']} (refresh one or the other)")
        elif (item["value"] is None) != (r["value"] is None) or (
                item["value"] is not None and abs(item["value"] - r["value"]) > 0.0005):
            errors.append(f"groceries {key}: ours={item['value']} reference={r['value']}")
    return errors, checked


def check_alignment(wages: dict, rent: dict, gas: dict, owner: dict | None = None) -> list[str]:
    w, r, g = set(wages["metros"]), set(rent["metros"]), set(gas["metros"])
    errors = []
    if w != r:
        errors.append(f"rent/wage metro mismatch: only wages {sorted(w - r)[:5]}, only rent {sorted(r - w)[:5]}")
    if not g <= w:
        errors.append(f"gas metros not in wages: {sorted(g - w)}")
    if owner is not None and (o := set(owner["metros"])) != w:
        errors.append(f"owner/wage metro mismatch: only wages {sorted(w - o)[:5]}, only owner {sorted(o - w)[:5]}")
    return errors


def check_ranges(wages: dict, rent: dict, gas: dict, owner: dict | None = None) -> list[str]:
    warnings = []

    def chk(kind, code, label, v):
        lo, hi = RANGES[kind]
        if v is not None and not lo <= v <= hi:
            warnings.append(f"{code} {label}={v} outside [{lo}, {hi}]")

    for code, m in wages["metros"].items():
        chk("wage", code, "hourly_median", value_of(m["hourly_median"]))
    for code, m in rent["metros"].items():
        for k in RENT_KEYS:
            chk("rent", code, k, value_of(m[k]))
    for code, m in gas["metros"].items():
        chk("gas", code, "price_per_gallon", value_of(m["price_per_gallon"]))
    for code, m in (owner or {}).get("metros", {}).items():
        chk("home_value", code, "home_value", value_of(m["home_value"]))
        chk("owner_cost", code, "owner_cost_with_mortgage", value_of(m["owner_cost_with_mortgage"]))
    return warnings


def compare(ours: dict, ref: dict, tol: float) -> tuple[list[str], set]:
    """ours/ref: {code: value|None}. Returns (mismatch errors, codes checked)."""
    errors, checked = [], set()
    for code, v in ours.items():
        if code not in ref:
            continue
        checked.add(code)
        rv = ref[code]
        if (v is None) != (rv is None) or (v is not None and abs(v - rv) > tol):
            errors.append(f"{code}: ours={v} reference={rv}")
    return errors, checked


def check_references(wages, rent, gas, refs, owner: dict | None = None) -> tuple[list[str], dict]:
    """Returns (errors, {code: set of measures checked})."""
    errors, checked = [], {}
    pairs = [
        ("wage", "bls_oews_hourly_median", {c: value_of(m["hourly_median"]) for c, m in wages["metros"].items()}, 0.005),
        ("rent", "census_b25064", {c: value_of(m["all_units"]) for c, m in rent["metros"].items()}, 0.5),
        ("gas", "eia_html", {c: value_of(m["price_per_gallon"]) for c, m in gas["metros"].items()}, 0.0005),
    ]
    if owner is not None:
        pairs.append(("home_value", "census_b25097",
                      {c: value_of(m["home_value"]) for c, m in owner["metros"].items()}, 0.5))
    for label, key, ours, tol in pairs:
        ref = refs.get(key)
        if not ref:
            errors.append(f"{label}: no reference data ({key}); run with --refresh-references")
            continue
        if label == "gas":
            expected = dt.datetime.strptime(gas["as_of"], "%Y-%m").strftime("%b-%y")
            if ref.get("period") != expected:
                errors.append(f"gas: reference period {ref.get('period')} != data period {expected}")
        errs, codes = compare(ours, ref["values"], tol)
        errors += [f"{label} {e}" for e in errs]
        for c in codes:
            checked.setdefault(c, set()).add(label)
    return errors, checked


# ---------- report ----------

def hours(cost, wage):
    return round(cost / wage, 2) if cost is not None and wage else None


def report_rows(wages, rent, gas, checked, owner: dict | None = None) -> list[dict]:
    rows = []
    for code in sorted(wages["metros"]):
        w, r, g = wages["metros"][code], rent["metros"].get(code, {}), gas["metros"].get(code)
        o = (owner or {}).get("metros", {}).get(code, {})
        wage = value_of(w["hourly_median"])
        rents = {k: value_of(r.get(k)) for k in RENT_KEYS}
        price = value_of(g["price_per_gallon"]) if g else None
        missing = [n for n, v in [("wage", wage), ("rent_all_units", rents["all_units"]),
                                  ("rent_1br", rents["one_bedroom"]), ("rent_2br", rents["two_bedroom"]),
                                  ("gas", price)] if v is None]
        if owner is not None:
            home, cost = value_of(o.get("home_value")), value_of(o.get("owner_cost_with_mortgage"))
            missing += [n for n, v in [("home_value", home), ("owner_cost", cost)] if v is None]
        row = {
            "cbsa": code,
            "name": r.get("name") or w["name"],  # ACS names keep diacritics
            "wage_hourly_median": wage, "wage_as_of": wages["as_of"],
            "rent_all_units": rents["all_units"], "rent_1br": rents["one_bedroom"], "rent_2br": rents["two_bedroom"],
            "rent_as_of": rent["as_of"],
            "gas_per_gallon": price, "gas_as_of": gas["as_of"] if price is not None else "",
            "hours_rent_all_units": hours(rents["all_units"], wage),
            "hours_per_gallon": hours(price, wage),
            "measures_missing": ";".join(missing),
            "reference_checked": ";".join(sorted(checked.get(code, ()))),
        }
        if owner is not None:
            row.update({"home_value": home, "owner_cost_with_mortgage": cost, "owner_as_of": owner["as_of"],
                        "hours_owner_cost": hours(cost, wage)})
        rows.append(row)
    return rows


def write_report(rows, path: Path = REPORT_PATH):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for row in rows:
            w.writerow({k: "" if v is None else v for k, v in row.items()})


# ---------- reference fetching ----------

def _get(url: str, ua: str, data: bytes | None = None) -> bytes:
    headers = {"User-Agent": ua}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
        return resp.read()


def bls_series_id(cbsa: str) -> str:
    """OEWS series: OEU + area type M + 7-digit area + industry + occupation + datatype 08 (hourly median)."""
    return f"OEUM{int(cbsa):07d}00000000000008"


def parse_bls_response(payload: dict, year: str) -> dict:
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API: {payload.get('status')} {payload.get('message')}")
    out = {}
    for s in payload["Results"]["series"]:
        cbsa = s["seriesID"][4:11].lstrip("0").zfill(5)
        hit = next((d for d in s["data"] if d["year"] == year), None)
        try:
            out[cbsa] = float(hit["value"]) if hit else None
        except ValueError:  # e.g. "-" or "#"
            out[cbsa] = None
    return out


def parse_eia_html(html: str) -> tuple[str, dict]:
    """Returns (latest month label like 'Oct-26', {label: latest value}) from the Cities section."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&nbsp;", " ")
    months = re.findall(r"\b[A-Z][a-z]{2}-\d{2}\b", text)
    if not months:
        raise ValueError("EIA HTML: no month headers found")
    cities = text[text.index(" Cities "):] if " Cities " in text else text
    out = {}
    for label in EIA_CITY_LABELS:
        m = re.search(re.escape(label) + r"((?: [0-9.]+| NA| W| -){6})", cities)
        if m:
            last = m.group(1).split()[-1]
            out[label] = float(last) if re.fullmatch(r"[0-9.]+", last) else None
    return months[5] if len(months) >= 6 else months[-1], out


def _census_column(url: str, column: str, metros: dict, top_code: int) -> dict:
    """Read one column of a Census table-based summary file for our metros."""
    lines = _get(url, "time-to-afford/0.1").decode("utf-8").splitlines()
    hdr = lines[0].split("|")
    vals = {}
    for ln in lines[1:]:
        row = dict(zip(hdr, ln.split("|")))
        gid = row["GEO_ID"]
        if gid.startswith("310M") and gid[-5:] in metros:
            v = int(row[column])
            vals[gid[-5:]] = v if 0 <= v != top_code else None
    return vals


def fetch_wage_reference(wages: dict, contact: str, today: str) -> dict:
    """BLS API v1: 16 requests for ~393 metros (daily limit 25)."""
    ua = f"time-to-afford/0.1 (contact: {contact})"
    year = wages["as_of"][:4]
    codes = sorted(wages["metros"])
    values = {}
    for i in range(0, len(codes), BLS_BATCH):
        body = json.dumps({"seriesid": [bls_series_id(c) for c in codes[i:i + BLS_BATCH]],
                           "startyear": year, "endyear": year}).encode()
        values.update(parse_bls_response(json.loads(_get(BLS_API, ua, body)), year))
        time.sleep(1)
    return {"source_url": BLS_API, "series": "OEUM{area}00000000000008",
            "period": f"May {year}", "retrieved": today, "values": values}


def fetch_rent_reference(rent: dict, today: str) -> dict:
    url = CENSUS_TABLE.format(y=rent["as_of"], t="b25064")
    return {"source_url": url, "period": rent["as_of"], "retrieved": today,
            "values": _census_column(url, "B25064_E001", rent["metros"], 3501)}


def fetch_gas_reference(gas: dict, today: str) -> dict:
    month, by_label = parse_eia_html(_get(EIA_HTML, "time-to-afford/0.1").decode("utf-8", "replace"))
    label_to_cbsa = {m["eia_area"].split(",")[0]: c for c, m in gas["metros"].items()}
    vals = {label_to_cbsa[lbl]: v for lbl, v in by_label.items() if lbl in label_to_cbsa}
    return {"source_url": EIA_HTML, "period": month, "retrieved": today, "values": vals}


def fetch_owner_reference(owner: dict, today: str) -> dict:
    """B25097_E001 (median value, all owner-occupied units) should equal B25077_E001."""
    url = CENSUS_TABLE.format(y=owner["as_of"], t="b25097")
    return {"source_url": url, "column": "B25097_E001", "period": owner["as_of"], "retrieved": today,
            "values": _census_column(url, "B25097_E001", owner["metros"], 2000001)}


def fetch_groceries_reference(groceries: dict, contact: str, today: str) -> dict:
    import groceries as grocery_module  # local import: only needed when refreshing
    ua = f"time-to-afford/0.1 (contact: {contact})"
    lines = _get(BLS_AP_FLAT, ua).decode("utf-8").splitlines()
    wanted = {i["series"] for i in groceries["items"].values()}
    latest = grocery_module.latest_from_flat(lines, wanted)
    return {"source_url": BLS_AP_FLAT, "retrieved": today,
            "values": {s: {"as_of": f"{y}-{m:02d}", "value": v} for s, (y, m, v) in latest.items()}}


REFERENCE_KEYS = {"wage": "bls_oews_hourly_median", "rent": "census_b25064", "gas": "eia_html",
                  "owner": "census_b25097", "groceries": "bls_ap_flat"}


def fetch_references(sources, wages, rent, gas, owner, contact, groceries=None) -> dict:
    """Fetch the requested reference sources; returns {reference key: data}."""
    today = dt.date.today().isoformat()
    out = {}
    if "wage" in sources:
        out[REFERENCE_KEYS["wage"]] = fetch_wage_reference(wages, contact, today)
    if "rent" in sources:
        out[REFERENCE_KEYS["rent"]] = fetch_rent_reference(rent, today)
    if "gas" in sources:
        out[REFERENCE_KEYS["gas"]] = fetch_gas_reference(gas, today)
    if "owner" in sources and owner is not None:
        out[REFERENCE_KEYS["owner"]] = fetch_owner_reference(owner, today)
    if "groceries" in sources and groceries is not None:
        out[REFERENCE_KEYS["groceries"]] = fetch_groceries_reference(groceries, contact, today)
    return out


# ---------- entry point ----------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--refresh-references", nargs="*", choices=REFERENCE_SOURCES, metavar="SOURCE",
                   help="re-fetch reference values: all, or any of wage rent gas owner")
    p.add_argument("--contact", default=os.environ.get("BLS_CONTACT"))
    args = p.parse_args(argv)

    wages, rent, gas = load("wages.json"), load("rent.json"), load("gas.json")
    owner = load("owner.json") if (DATA / "owner.json").exists() else None
    groceries = load("groceries.json") if (DATA / "groceries.json").exists() else None
    grocery_metro = load("grocery_metro.json") if (DATA / "grocery_metro.json").exists() else None

    refs = json.loads(REF_PATH.read_text()) if REF_PATH.exists() else {}
    if args.refresh_references is not None:
        sources = set(args.refresh_references or REFERENCE_SOURCES)
        if sources & {"wage", "groceries"} and not args.contact:
            p.error("refreshing wage or groceries references requires --contact or BLS_CONTACT")
        refs.update(fetch_references(sources, wages, rent, gas, owner, args.contact, groceries))  # keep the others
        REF_PATH.parent.mkdir(parents=True, exist_ok=True)
        REF_PATH.write_text(json.dumps(refs, indent=2) + "\n")

    errors = (check_structure("wages", wages, ["hourly_median", "hourly_mean", "employment"])
              + check_structure("rent", rent, list(RENT_KEYS))
              + check_structure("gas", gas, ["price_per_gallon"])
              + check_alignment(wages, rent, gas, owner))
    if owner is not None:
        errors += check_structure("owner", owner, list(OWNER_KEYS))
    warnings = check_ranges(wages, rent, gas, owner)
    ref_errors, checked = check_references(wages, rent, gas, refs, owner)
    errors += ref_errors
    grocery_checked = 0
    if groceries is not None:
        errors += check_national("groceries", groceries)
        warnings += check_grocery_ranges(groceries)
        g_errors, grocery_checked = check_grocery_reference(groceries, refs)
        errors += g_errors
        if grocery_metro is not None:
            gm_errors, gm_warnings = check_grocery_metro(grocery_metro, groceries, wages)
            errors += gm_errors
            warnings += gm_warnings

    rows = report_rows(wages, rent, gas, checked, owner)
    write_report(rows)

    complete = sum(1 for r in rows if not r["measures_missing"])
    by_measure = {}
    for r in rows:
        for m in filter(None, r["measures_missing"].split(";")):
            by_measure[m] = by_measure.get(m, 0) + 1
    by_check = {k: sum(k in s for s in checked.values()) for k in ("wage", "rent", "gas", "home_value")}
    print(f"Metros: {len(rows)}; complete (all measures): {complete}; missing by measure: {by_measure}")
    print(f"Reference-checked metros: {by_check}")
    if groceries is not None:
        print(f"Groceries (national): {len(groceries['items'])} items, {grocery_checked} reference-checked, "
              f"{groceries['reference_period']}")
    if groceries is not None and grocery_metro is not None:
        print(f"Grocery estimates: {len(grocery_metro['metros'])} metros (RPP {grocery_metro['rpp_year']}), "
              f"recomputed from national prices")
    print(f"Report: {REPORT_PATH}")
    for w in warnings:
        print("WARNING", w)
    for e in errors:
        print("ERROR", e)
    print("FAILED" if errors else "PASSED", f"({len(errors)} errors, {len(warnings)} warnings)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
