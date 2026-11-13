import datetime as dt
import json

import pytest

import groceries
import tiers

SERIES = ["APU0000709112", "APU0000708111", "APU0000702111", "APU0000703112", "APU0000711211", "APU0000717311"]


def api_payload(rows):
    """rows: {series: [(year, period, value), ...]}"""
    return {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
        {"seriesID": s, "data": [{"year": str(y), "period": p, "value": v} for y, p, v in obs]}
        for s, obs in rows.items()]}}


def test_real_basket_file_loads():
    b = groceries.load_basket()
    assert b["version"] == 1 and b["geography"] == "US"
    assert [i["key"] for i in b["items"]] == ["milk", "eggs", "bread", "ground_beef", "bananas", "coffee"]
    assert [i["series"] for i in b["items"]] == SERIES


@pytest.mark.parametrize("bad, match", [
    ("version: 1\nitems: []\n", "no items"),
    ("version: x\nitems: [{key: a}]\n", "version"),
    ("version: 1\nitems:\n  - {key: a, label: A, series: APU0000709112, unit: lb, quantity: 1}\n"
     "  - {key: a, label: B, series: APU0000708111, unit: lb, quantity: 1}\n", "duplicate"),
    ("version: 1\nitems:\n  - {key: a, label: A, series: XYZ, unit: lb, quantity: 1}\n", "series"),
    ("version: 1\nitems:\n  - {key: a, label: A, series: APU0000709112, unit: lb, quantity: 0}\n", "quantity"),
    ("version: 1\nitems:\n  - {key: a, label: A, series: APU0000709112, unit: lb}\n", "missing"),
])
def test_basket_validation(tmp_path, bad, match):
    f = tmp_path / "b.yml"
    f.write_text(bad)
    with pytest.raises(ValueError, match=match):
        groceries.load_basket(f)


def test_latest_from_api_picks_latest_month_and_skips_annual():
    payload = api_payload({
        "APU0000709112": [(2026, "M09", "4.106"), (2026, "M10", "4.101"), (2025, "M13", "3.9")],
        "APU0000708111": [(2026, "M10", "-")],
    })
    out = groceries.latest_from_api(payload)
    assert out["APU0000709112"] == (2026, 10, 4.101)
    assert out["APU0000708111"] == (2026, 10, None)


def test_latest_from_api_error():
    with pytest.raises(RuntimeError):
        groceries.latest_from_api({"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold"]})


def test_latest_from_flat():
    lines = ["series_id        \tyear\tperiod\t       value\tfootnote_codes",
             "APU0000709112    \t2026\tM09\t       4.106\t",
             "APU0000709112    \t2026\tM10\t       4.101\t",
             "APU0000709112    \t2026\tM13\t       4.000\t",
             "APU0100709112    \t2026\tM10\t       4.500\t",  # regional series, not wanted
             "APU0000708111    \t2025\tM12\t       2.100\t"]
    out = groceries.latest_from_flat(lines, {"APU0000709112", "APU0000708111"})
    assert out == {"APU0000709112": (2026, 10, 4.101), "APU0000708111": (2025, 12, 2.1)}


def test_items_observed_with_own_as_of_and_missing_not_filled():
    basket = groceries.load_basket()
    latest = {"APU0000709112": (2026, 10, 4.101), "APU0000708111": (2026, 9, 2.272),
              "APU0000702111": (2026, 10, None)}
    items, methods = groceries.build_items(basket, latest, "http://x")
    assert items["milk"]["value"] == 4.101 and items["milk"]["tier"] == "observed"
    assert items["milk"]["method"] == "bls_ap_milk" and methods["bls_ap_milk"]["as_of"] == "2026-10"
    assert methods["bls_ap_eggs"]["as_of"] == "2026-09"  # each item keeps its own month
    assert items["bread"] == {**items["bread"], "value": None, "status": "missing"}
    assert items["coffee"]["status"] == "missing" and methods["bls_ap_coffee"]["as_of"] == "unavailable"
    for i in items.values():
        assert tiers.check_value(i["label"], i, methods) == []


def test_output_metadata():
    basket = groceries.load_basket()
    latest = {s: (2026, 10, 1.0) for s in SERIES}
    items, methods = groceries.build_items(basket, latest, "http://x")
    out = groceries.build_output(basket, items, methods, dt.date(2026, 11, 13), "http://x")
    assert out["geography"] == "US" and out["basket_version"] == 1
    assert out["as_of"] == "2026-10" and out["reference_period"] == "October 2026"
    assert out["items_same_month"] is True
    assert tiers.check_methods("groceries", out["methods"]) == []
    latest["APU0000717311"] = (2026, 9, 9.3)
    items, methods = groceries.build_items(basket, latest, "http://x")
    assert groceries.build_output(basket, items, methods, dt.date(2026, 11, 13), "http://x")["items_same_month"] is False


def test_main_with_flat_file(tmp_path):
    f = tmp_path / "ap.data.3.Food"
    f.write_text("series_id\tyear\tperiod\tvalue\tfootnote_codes\n" +
                 "".join(f"{s}\t2026\tM10\t{1 + n}.5\t\n" for n, s in enumerate(SERIES)))
    out = tmp_path / "g.json"
    assert groceries.main(["--file", str(f), "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["items"]["milk"]["value"] == 1.5 and data["items"]["coffee"]["value"] == 6.5
    assert data["methods"]["bls_ap_milk"]["inputs"][0]["url"] == groceries.FLAT_FILE_URL


def test_api_requires_contact(monkeypatch):
    monkeypatch.delenv("BLS_CONTACT", raising=False)
    with pytest.raises(SystemExit):
        groceries.main([])
