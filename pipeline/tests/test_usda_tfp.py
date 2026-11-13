import datetime as dt
import urllib.error

import pytest

import tiers
import usda_tfp

SAMPLE = """USDA Food and Nutrition Administration
Official USDA Thrifty Food Plan:
U.S. Average, October 2026 1
Age-Sex Groups2 Weekly Cost3 Monthly Cost3
Child:
1 year $26.40 $114.20
6-8 years $48.30 $209.30
9-11 years $55.80 $242.00
Female:
12-13 years $51.70 $223.90
20-50 years $58.70 $254.20
Male:
20-50 years $73.70 $319.10
71+ years $62.00 $268.70
Reference Family:4
Male and Female, 20–50 years
and Two Children, 6–8 and 9–11 years $236.50 $1,024.60
3 All costs are rounded to nearest 10 cents.
"""


def test_parse_report():
    r = usda_tfp.parse_report(SAMPLE)
    assert r["month"] == dt.date(2026, 10, 1)
    assert r["weekly"] == 236.5 and r["monthly"] == 1024.6
    assert r["members"] == {"child_6_8": 209.3, "child_9_11": 242.0, "female_20_50": 254.2, "male_20_50": 319.1}
    assert usda_tfp.check_report(r) == []


def test_members_must_add_up():
    r = usda_tfp.parse_report(SAMPLE.replace("$1,024.60", "$1,124.60"))
    assert "members sum to $1,024.60" in usda_tfp.check_report(r)[0]


@pytest.mark.parametrize("broken, match", [
    ("U.S. Average, October 2026", "heading"),
    ("and Two Children, 6–8 and 9–11 years $236.50 $1,024.60", "reference family"),
    ("20-50 years $73.70 $319.10", "male_20_50"),
])
def test_parse_fails_loudly(broken, match):
    with pytest.raises(ValueError, match=match):
        usda_tfp.parse_report(SAMPLE.replace(broken, ""))


def test_output_tagged_observed_national():
    out = usda_tfp.build_output(usda_tfp.parse_report(SAMPLE), "http://x.pdf", dt.date(2026, 11, 13))
    assert out["as_of"] == "2026-10" and out["geography"] == "US" and out["reference_period"] == "October 2026"
    v = out["reference_family_monthly"]
    assert v == {"value": 1024.6, "status": "ok", "tier": "observed", "method": usda_tfp.METHOD}
    assert tiers.check_methods("tfp", out["methods"]) == []
    assert tiers.check_value("tfp", v, out["methods"]) == []
    assert "not part of the grocery basket" in out["basis"]


def test_months_back_crosses_year():
    assert [d.strftime("%Y-%m") for d in usda_tfp.months_back(dt.date(2026, 2, 13), 3)] == \
        ["2026-02", "2026-01", "2025-12", "2025-11"]


def test_download_latest_skips_missing_months(monkeypatch, tmp_path):
    calls = []

    class Resp:
        def __init__(self, data): self.data = data
        def read(self): return self.data
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_open(req, timeout, context):
        calls.append(req.full_url)
        if "Nov2026" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        return Resp(b"%PDF-1.6 fake")

    monkeypatch.setattr(usda_tfp.urllib.request, "urlopen", fake_open)
    path, url = usda_tfp.download_latest(dt.date(2026, 11, 13), tmp_path)
    assert url.endswith("CostofFoodOct2026Thrifty.pdf") and path.read_bytes().startswith(b"%PDF")
    assert len(calls) == 2


def test_main_with_file(monkeypatch, tmp_path):
    pdf = tmp_path / "CostofFoodOct2026Thrifty.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(usda_tfp, "pdf_text", lambda p: SAMPLE)
    out = tmp_path / "t.json"
    assert usda_tfp.main(["--file", str(pdf), "--out", str(out)]) == 0
    import json
    d = json.loads(out.read_text())
    assert d["methods"][usda_tfp.METHOD]["inputs"][0]["url"].endswith("CostofFoodOct2026Thrifty.pdf")
    monkeypatch.setattr(usda_tfp, "pdf_text", lambda p: SAMPLE.replace("$1,024.60", "$900.00"))
    assert usda_tfp.main(["--file", str(pdf), "--out", str(out)]) == 1


REAL = usda_tfp.RAW_DIR / "CostofFoodOct2026Thrifty.pdf"


@pytest.mark.skipif(not REAL.exists(), reason="raw report not downloaded (data/raw is not committed)")
def test_real_october_2026_report():
    r = usda_tfp.parse_report(usda_tfp.pdf_text(REAL))
    assert r["monthly"] == 1024.6 and usda_tfp.check_report(r) == []
