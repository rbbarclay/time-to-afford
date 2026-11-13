"""USDA Thrifty Food Plan (to-do 4b): national reference line -> data/usda_tfp.json.

Reads the monthly "Official USDA Thrifty Food Plan: U.S. Average" report (PDF
only) and takes the monthly cost for the reference family of four (male and
female 20-50, children 6-8 and 9-11). This is a national reference figure,
never a metro value, and is never added to the grocery basket.

Check on every run: the four family members' monthly costs, printed in the same
report, must add up to the reference family's monthly cost (within rounding).

Usage:
  python pipeline/usda_tfp.py                 # find the latest report (this month back to 4 months ago)
  python pipeline/usda_tfp.py --file PATH     # a local report PDF
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import certifi

from tiers import method_entry, tag

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "usda"
OUT_PATH = ROOT / "data" / "usda_tfp.json"

REPORTS_PAGE = "https://www.fna.usda.gov/research/cnpp/usda-food-plans/cost-food-monthly-reports"
PDF_URL = "https://www.fna.usda.gov/sites/default/files/resource-files/CostofFood{mon}{year}Thrifty.pdf"
METHOD = "usda_tfp_reference_family"
ROUNDING_TOLERANCE = 0.25  # each published cost is rounded to the nearest 10 cents

MONEY = r"\$([\d,]+\.\d{2})"
MEMBERS = {  # (section heading, age row) -> key
    ("Male", "20-50 years"): "male_20_50",
    ("Female", "20-50 years"): "female_20_50",
    ("Child", "6-8 years"): "child_6_8",
    ("Child", "9-11 years"): "child_9_11",
}


def _money(s: str) -> float:
    return float(s.replace(",", ""))


def _dashes(s: str) -> str:
    return s.replace("–", "-").replace("—", "-")


def parse_report(text: str) -> dict:
    """Month, reference-family weekly/monthly cost, and the four members' monthly costs."""
    text = _dashes(text)
    m = re.search(r"Thrifty Food Plan:\s*U\.S\. Average,\s*([A-Z][a-z]+ \d{4})", text)
    if not m:
        raise ValueError("report heading 'Thrifty Food Plan: U.S. Average, <Month YYYY>' not found")
    month = dt.datetime.strptime(m.group(1), "%B %Y").date()

    fam = re.search(r"Reference Family.*?and Two Children,?\s*6-8 and 9-11 years\s*" + MONEY + r"\s*" + MONEY,
                    text, re.S)
    if not fam:
        raise ValueError("reference family row not found")

    members, section = {}, None
    for line in text.splitlines():
        line = line.strip()
        head = re.match(r"^(Child|Female|Male):", line)
        if head:
            section = head.group(1)
            continue
        if line.startswith("Reference Family"):
            break
        row = re.match(r"^(\d+(?:-\d+)? years)\s*" + MONEY + r"\s*" + MONEY, line)
        if row and (section, row.group(1)) in MEMBERS:
            members[MEMBERS[(section, row.group(1))]] = _money(row.group(3))
    missing = set(MEMBERS.values()) - set(members)
    if missing:
        raise ValueError(f"member rows not found: {sorted(missing)}")
    return {"month": month, "weekly": _money(fam.group(1)), "monthly": _money(fam.group(2)), "members": members}


def check_report(parsed: dict) -> list[str]:
    total = round(sum(parsed["members"].values()), 2)
    if abs(total - parsed["monthly"]) > ROUNDING_TOLERANCE:
        return [f"family members sum to ${total:,.2f}, but the reference family is ${parsed['monthly']:,.2f}"]
    return []


def pdf_text(path: Path) -> str:
    import pypdf  # local import: only needed when reading a report
    reader = pypdf.PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def build_output(parsed: dict, source_url: str, retrieved: dt.date) -> dict:
    as_of = parsed["month"].strftime("%Y-%m")
    return {
        "source": "U.S. Department of Agriculture, Official USDA Thrifty Food Plan: U.S. Average",
        "source_url": REPORTS_PAGE,
        "geography": "US",
        "reference_period": parsed["month"].strftime("%B %Y"),
        "as_of": as_of,
        "retrieved": retrieved.isoformat(),
        "basis": ("USDA's monthly cost of a nutritious, low-cost diet with all meals prepared at home, for a "
                  "reference family of four (two adults 20-50, children 6-8 and 9-11). National reference "
                  "line only: not a metro value and not part of the grocery basket."),
        "attribution": "Source: USDA, Thrifty Food Plan cost of food report",
        "methods": {METHOD: method_entry(
            ("USDA Thrifty Food Plan, U.S. average monthly cost for the reference family of four "
             "(male and female 20-50, children 6-8 and 9-11), as published"),
            [{"source": "usda_tfp", "url": source_url, "row": "Reference Family, Monthly Cost"}],
            as_of)},
        "reference_family_monthly": tag({"value": parsed["monthly"], "status": "ok"}, "observed", METHOD),
        "reference_family_weekly": tag({"value": parsed["weekly"], "status": "ok"}, "observed", METHOD),
        "members_monthly": parsed["members"],
    }


def months_back(today: dt.date, n: int):
    y, m = today.year, today.month
    for _ in range(n + 1):
        yield dt.date(y, m, 1)
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)


def download_latest(today: dt.date, dest_dir: Path = RAW_DIR, back: int = 4) -> tuple[Path, str]:
    ctx = ssl.create_default_context(cafile=certifi.where())
    for d in months_back(today, back):
        url = PDF_URL.format(mon=d.strftime("%b"), year=d.year)
        req = urllib.request.Request(url, headers={"User-Agent": "time-to-afford/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                data = resp.read()
        except urllib.error.HTTPError as err:
            if err.code == 404:
                continue
            raise
        if not data.startswith(b"%PDF"):
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / url.rsplit("/", 1)[1]
        dest.write_bytes(data)
        return dest, url
    raise RuntimeError(f"no Thrifty Food Plan report found for the last {back + 1} months")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path, help="local Thrifty Food Plan report PDF")
    p.add_argument("--out", type=Path, default=OUT_PATH)
    args = p.parse_args(argv)

    if args.file:
        path, retrieved = args.file, dt.date.fromtimestamp(args.file.stat().st_mtime)
        url = PDF_URL.format(mon="{Mon}", year="{YYYY}")
        m = re.match(r"CostofFood([A-Z][a-z]{2})(\d{4})Thrifty\.pdf$", path.name)
        if m:
            url = PDF_URL.format(mon=m.group(1), year=m.group(2))
    else:
        path, url = download_latest(dt.date.today())
        retrieved = dt.date.today()

    parsed = parse_report(pdf_text(path))
    if errors := check_report(parsed):
        for e in errors:
            print("ERROR", e, file=sys.stderr)
        return 1
    out = build_output(parsed, url, retrieved)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote Thrifty Food Plan {out['reference_period']}: reference family ${parsed['monthly']:,.2f}/month "
          f"(members sum ${sum(parsed['members'].values()):,.2f}) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
