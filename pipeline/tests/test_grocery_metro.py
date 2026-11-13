import csv
import datetime as dt
import io
import zipfile

import pytest

import grocery_metro as gm
import tiers


def rpp_rows(extra=()):
    header = ["GeoFIPS", "GeoName", "Region", "TableName", "LineCode", "IndustryClassification", "Description",
              "Unit", "2023", "2024"]
    rows = [
        [' "00000"', "United States", "", "MARPP", "2", "...", "RPPs: Goods", "Index", "100.0", "100.0"],
        [' "00999"', "Nonmetropolitan portion", "", "MARPP", "2", "...", "RPPs: Goods", "Index", "93.0", "93.0"],
        [' "35620"', "New York-Newark-Jersey City, NY-NJ (Metropolitan Statistical Area)", "", "MARPP", "1", "...",
         "RPPs: All items", "Index", "112.0", "112.563"],
        [' "35620"', "New York-Newark-Jersey City, NY-NJ (Metropolitan Statistical Area)", "", "MARPP", "2", "...",
         "RPPs: Goods", "Index", "109.9", "110.261"],
        [' "21420"', "Enid, OK (Metropolitan Statistical Area) *", "", "MARPP", "2", "...", "RPPs: Goods", "Index",
         "94.0", "94.5"],
        [' "99998"', "Nowhere, ZZ (Metropolitan Statistical Area)", "", "MARPP", "2", "...", "RPPs: Goods", "Index",
         "(NA)", "(NA)"],
        *extra,
    ]
    return [dict(zip(header, r)) for r in rows]


def groceries(milk=4.0, eggs_status="ok"):
    meth = lambda m: {"description": m, "inputs": [{"source": "bls_ap"}], "as_of": "2026-10"}
    return {
        "as_of": "2026-10", "reference_period": "October 2026", "basket_version": 1,
        "methods": {"bls_ap_milk": meth("milk"), "bls_ap_eggs": meth("eggs")},
        "items": {
            "milk": {"label": "Milk, whole", "series": "APU0000709112", "value": milk, "status": "ok",
                     "tier": "observed", "method": "bls_ap_milk"},
            "eggs": {"label": "Eggs", "series": "APU0000708111",
                     "value": 2.0 if eggs_status == "ok" else None, "status": eggs_status,
                     "tier": "observed", "method": "bls_ap_eggs"},
        },
    }


def test_goods_rpp_latest_year_metros_only():
    year, rpp = gm.goods_rpp(rpp_rows())
    assert year == 2024
    assert set(rpp) == {"35620", "21420", "99998"}  # U.S. and nonmetro rows dropped, line 1 ignored
    assert rpp["35620"] == ("New York-Newark-Jersey City, NY-NJ", 110.261)
    assert rpp["21420"] == ("Enid, OK", 94.5)  # footnote mark removed
    assert rpp["99998"][1] is None  # (NA)
    assert gm.goods_rpp(rpp_rows(), 2023)[1]["35620"][1] == 109.9


def test_goods_line_description_is_verified():
    bad = rpp_rows([[' "11111"', "X (Metropolitan Statistical Area)", "", "MARPP", "2", "...", "RPPs: Food",
                     "Index", "1", "1"]])
    with pytest.raises(ValueError, match="expected 'RPPs: Goods'"):
        gm.goods_rpp(bad)


def test_estimates_are_national_times_rpp_and_labeled_estimated():
    year, rpp = gm.goods_rpp(rpp_rows())
    metros, methods = gm.build(groceries(), year, rpp, "http://bea/MARPP.zip")
    ny = metros["35620"]
    assert ny["rpp_goods"] == {"value": 110.261, "status": "ok", "tier": "observed", "method": "bea_rpp_goods"}
    assert ny["items"]["milk"] == {"value": round(4.0 * 110.261 / 100, 3), "status": "ok",
                                   "tier": "estimated", "method": "est_rpp_goods_milk"}
    m = methods["est_rpp_goods_milk"]
    assert "all-goods" in m["description"] and "approximation" in m["description"]
    assert m["as_of"] == "2026-10"
    assert m["inputs"][0] == {"source": "bls_ap", "series": "APU0000709112", "as_of": "2026-10"}
    assert m["inputs"][1]["year"] == 2024 and m["inputs"][1]["line"] == "2"
    assert tiers.check_methods("gm", methods) == []
    for metro in metros.values():
        assert tiers.check_value("rpp", metro["rpp_goods"], methods) == []
        for v in metro["items"].values():
            assert tiers.check_value("item", v, methods) == []


def test_missing_inputs_give_missing_estimates():
    year, rpp = gm.goods_rpp(rpp_rows())
    metros, _ = gm.build(groceries(eggs_status="missing"), year, rpp, "u")
    assert metros["35620"]["items"]["eggs"] == {"value": None, "status": "missing",
                                                "tier": "estimated", "method": "est_rpp_goods_eggs"}
    nowhere = metros["99998"]
    assert nowhere["rpp_goods"]["status"] == "missing"
    assert nowhere["items"]["milk"]["status"] == "missing"


def test_consistency_weighted_ratio():
    year, rpp = gm.goods_rpp(rpp_rows())
    metros, _ = gm.build(groceries(), year, rpp, "u")
    ratio = gm.consistency(metros, groceries(), {"35620": 3, "21420": 1})
    ny, enid = round(4.0 * 1.10261, 3), round(4.0 * 0.945, 3)  # stored estimates are rounded
    assert ratio["milk"] == round((ny * 3 + enid) / 4 / 4.0, 4)


def test_read_rpp_csv_from_zip(tmp_path):
    buf = io.StringIO()
    rows = rpp_rows()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    z = tmp_path / "MARPP.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("MARPP_MSA_2008_2024.csv", buf.getvalue())
        zf.writestr("MAIRPD_MSA_2008_2024.csv", "ignored")
    name, read = gm.read_rpp_csv(z)
    assert name == "MARPP_MSA_2008_2024.csv"
    assert gm.goods_rpp(read)[1]["35620"][1] == 110.261


def test_output_metadata():
    year, rpp = gm.goods_rpp(rpp_rows())
    metros, methods = gm.build(groceries(), year, rpp, "u")
    out = gm.build_output(metros, methods, groceries(), year, dt.date(2026, 11, 13))
    assert out["as_of"] == "2026-10" and out["rpp_year"] == 2024
    assert "Not observed" in out["basis"] and "Puerto Rico" in out["coverage_note"]


def _gm_doc():
    year, rpp = gm.goods_rpp(rpp_rows())
    del rpp["99998"]
    metros, methods = gm.build(groceries(), year, rpp, "u")
    return gm.build_output(metros, methods, groceries(), year, dt.date(2026, 11, 13))


def _wages():
    emp = lambda n: {"value": n, "status": "ok", "tier": "observed", "method": "oews_employment"}
    return {"metros": {"35620": {"employment": emp(3)}, "21420": {"employment": emp(1)},
                       "41980": {"employment": emp(1)}}}


def test_validate_grocery_metro_passes_and_catches_problems():
    import validate
    doc = _gm_doc()
    errors, warnings = validate.check_grocery_metro(doc, groceries(), _wages())
    assert errors == []
    assert any("employment-weighted" in w for w in warnings)  # toy data: NY-heavy mean is 1.06x national

    doc["metros"]["35620"]["items"]["milk"]["value"] += 0.01  # no longer national x RPP
    doc["as_of"] = "2026-09"
    doc["metros"]["99999"] = doc["metros"]["21420"]
    errors, _ = validate.check_grocery_metro(doc, groceries(), _wages())
    assert any("35620.milk" in e and "national x RPP" in e for e in errors)
    assert any("national month 2026-09" in e for e in errors)
    assert any("not in wages" in e for e in errors)
