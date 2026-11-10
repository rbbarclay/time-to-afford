"""Validate data/wages.json, data/rent.json, data/gas.json across all metros.

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

Writes data/validation_report.csv: one row per metro with inputs, as-of dates,
hours of work (rent / median wage, gas per gallon / median wage), and the
measures that are missing.

Usage:
  python pipeline/validate.py                         # validate using stored references
  python pipeline/validate.py --refresh-references    # re-fetch references first (BLS_CONTACT or --contact required)
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

RANGES = {"wage": (8.0, 100.0), "rent": (300, 5000), "gas": (2.0, 9.0)}
RENT_KEYS = ("all_units", "one_bedroom", "two_bedroom")

BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_BATCH = 25  # API v1 limit: 25 series per request, 25 requests per day
CENSUS_B25064 = ("https://www2.census.gov/programs-surveys/acs/summary_file/{y}/table-based-SF/"
                 "data/1YRData/acsdt1y{y}-b25064.dat")
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


def check_alignment(wages: dict, rent: dict, gas: dict) -> list[str]:
    w, r, g = set(wages["metros"]), set(rent["metros"]), set(gas["metros"])
    errors = []
    if w != r:
        errors.append(f"rent/wage metro mismatch: only wages {sorted(w - r)[:5]}, only rent {sorted(r - w)[:5]}")
    if not g <= w:
        errors.append(f"gas metros not in wages: {sorted(g - w)}")
    return errors


def check_ranges(wages: dict, rent: dict, gas: dict) -> list[str]:
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


def check_references(wages, rent, gas, refs) -> tuple[list[str], dict]:
    """Returns (errors, {code: set of measures checked})."""
    errors, checked = [], {}
    pairs = [
        ("wage", "bls_oews_hourly_median", {c: value_of(m["hourly_median"]) for c, m in wages["metros"].items()}, 0.005),
        ("rent", "census_b25064", {c: value_of(m["all_units"]) for c, m in rent["metros"].items()}, 0.5),
        ("gas", "eia_html", {c: value_of(m["price_per_gallon"]) for c, m in gas["metros"].items()}, 0.0005),
    ]
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


def report_rows(wages, rent, gas, checked) -> list[dict]:
    rows = []
    for code in sorted(wages["metros"]):
        w, r, g = wages["metros"][code], rent["metros"].get(code, {}), gas["metros"].get(code)
        wage = value_of(w["hourly_median"])
        rents = {k: value_of(r.get(k)) for k in RENT_KEYS}
        price = value_of(g["price_per_gallon"]) if g else None
        missing = [n for n, v in [("wage", wage), ("rent_all_units", rents["all_units"]),
                                  ("rent_1br", rents["one_bedroom"]), ("rent_2br", rents["two_bedroom"]),
                                  ("gas", price)] if v is None]
        rows.append({
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
        })
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


def fetch_references(wages: dict, rent: dict, gas: dict, contact: str) -> dict:
    today = dt.date.today().isoformat()
    refs = {}

    # BLS API v1: 16 requests for ~393 metros (daily limit 25)
    ua = f"time-to-afford/0.1 (contact: {contact})"
    year = wages["as_of"][:4]
    codes = sorted(wages["metros"])
    values = {}
    for i in range(0, len(codes), BLS_BATCH):
        body = json.dumps({"seriesid": [bls_series_id(c) for c in codes[i:i + BLS_BATCH]],
                           "startyear": year, "endyear": year}).encode()
        values.update(parse_bls_response(json.loads(_get(BLS_API, ua, body)), year))
        time.sleep(1)
    refs["bls_oews_hourly_median"] = {"source_url": BLS_API, "series": "OEUM{area}00000000000008",
                                      "period": f"May {year}", "retrieved": today, "values": values}

    # Census B25064 (one file)
    y = rent["as_of"]
    url = CENSUS_B25064.format(y=y)
    lines = _get(url, "time-to-afford/0.1").decode("utf-8").splitlines()
    hdr = lines[0].split("|")
    vals = {}
    for ln in lines[1:]:
        row = dict(zip(hdr, ln.split("|")))
        gid = row["GEO_ID"]
        if gid.startswith("310M") and gid[-5:] in rent["metros"]:
            v = int(row["B25064_E001"])
            vals[gid[-5:]] = v if 0 <= v != 3501 else None
    refs["census_b25064"] = {"source_url": url, "period": y, "retrieved": today, "values": vals}

    # EIA HTML table (one page)
    month, by_label = parse_eia_html(_get(EIA_HTML, "time-to-afford/0.1").decode("utf-8", "replace"))
    label_to_cbsa = {m["eia_area"].split(",")[0]: c for c, m in gas["metros"].items()}
    vals = {label_to_cbsa[lbl]: v for lbl, v in by_label.items() if lbl in label_to_cbsa}
    refs["eia_html"] = {"source_url": EIA_HTML, "period": month, "retrieved": today, "values": vals}
    return refs


# ---------- entry point ----------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--refresh-references", action="store_true")
    p.add_argument("--contact", default=os.environ.get("BLS_CONTACT"))
    args = p.parse_args(argv)

    wages, rent, gas = load("wages.json"), load("rent.json"), load("gas.json")

    if args.refresh_references:
        if not args.contact:
            p.error("--refresh-references requires --contact or BLS_CONTACT")
        REF_PATH.parent.mkdir(parents=True, exist_ok=True)
        REF_PATH.write_text(json.dumps(fetch_references(wages, rent, gas, args.contact), indent=2) + "\n")
    refs = json.loads(REF_PATH.read_text()) if REF_PATH.exists() else {}

    errors = (check_structure("wages", wages, ["hourly_median", "hourly_mean", "employment"])
              + check_structure("rent", rent, list(RENT_KEYS))
              + check_structure("gas", gas, ["price_per_gallon"])
              + check_alignment(wages, rent, gas))
    warnings = check_ranges(wages, rent, gas)
    ref_errors, checked = check_references(wages, rent, gas, refs)
    errors += ref_errors

    rows = report_rows(wages, rent, gas, checked)
    write_report(rows)

    complete = sum(1 for r in rows if not r["measures_missing"])
    by_measure = {}
    for r in rows:
        for m in filter(None, r["measures_missing"].split(";")):
            by_measure[m] = by_measure.get(m, 0) + 1
    by_check = {k: sum(k in s for s in checked.values()) for k in ("wage", "rent", "gas")}
    print(f"Metros: {len(rows)}; complete (all measures): {complete}; missing by measure: {by_measure}")
    print(f"Reference-checked metros: {by_check}")
    print(f"Report: {REPORT_PATH}")
    for w in warnings:
        print("WARNING", w)
    for e in errors:
        print("ERROR", e)
    print("FAILED" if errors else "PASSED", f"({len(errors)} errors, {len(warnings)} warnings)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
