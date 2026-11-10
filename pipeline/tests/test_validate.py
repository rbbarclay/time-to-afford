import validate as v


def ok(x, method="m"):
    return {"value": x, "status": "ok", "tier": "observed", "method": method}


MISSING = {"value": None, "status": "missing", "tier": "observed", "method": "m"}
METHODS = {"m": {"description": "test method", "inputs": [{"source": "test"}], "as_of": "2025"}}


def sample():
    wages = {"as_of": "2025-05", "methods": METHODS, "metros": {
        "35620": {"name": "New York", "hourly_median": ok(29.53), "hourly_mean": ok(41.5), "employment": ok(1.0)},
        "41980": {"name": "San Juan-Bayamon", "hourly_median": ok(14.15), "hourly_mean": ok(19.0), "employment": ok(1.0)},
    }}
    rent = {"as_of": "2025", "methods": METHODS, "metros": {
        "35620": {"name": "New York", "all_units": ok(1932), "one_bedroom": ok(1774), "two_bedroom": ok(1997)},
        "41980": {"name": "San Juan-Bayamón", "all_units": ok(639), "one_bedroom": MISSING, "two_bedroom": ok(581)},
    }}
    gas = {"as_of": "2026-10", "methods": METHODS, "metros": {
        "35620": {"eia_area": "New York City", "price_per_gallon": ok(4.27)},
    }}
    return wages, rent, gas


def refs():
    return {
        "bls_oews_hourly_median": {"values": {"35620": 29.53, "41980": 14.15}},
        "census_b25064": {"values": {"35620": 1932, "41980": 639}},
        "eia_html": {"period": "Oct-26", "values": {"35620": 4.27}},
    }


def test_structure_ok_and_detects_problems():
    wages, rent, gas = sample()
    assert v.check_structure("rent", rent, list(v.RENT_KEYS)) == []
    rent["metros"]["35620"]["all_units"] = {"value": 5, "status": "missing"}
    rent["metros"]["123"] = rent["metros"].pop("41980")
    del rent["as_of"]
    errs = v.check_structure("rent", rent, list(v.RENT_KEYS))
    assert any("as_of" in e for e in errs)
    assert any("mismatch" in e for e in errs)
    assert any("5-digit" in e for e in errs)


def test_alignment():
    wages, rent, gas = sample()
    assert v.check_alignment(wages, rent, gas) == []
    gas["metros"]["99999"] = gas["metros"]["35620"]
    del rent["metros"]["41980"]
    errs = v.check_alignment(wages, rent, gas)
    assert len(errs) == 2


def test_ranges_warn_not_error():
    wages, rent, gas = sample()
    assert v.check_ranges(wages, rent, gas) == []
    gas["metros"]["35620"]["price_per_gallon"] = ok(12.0)
    assert len(v.check_ranges(wages, rent, gas)) == 1


def test_references_match_and_mismatch():
    wages, rent, gas = sample()
    errs, checked = v.check_references(wages, rent, gas, refs())
    assert errs == []
    assert checked["35620"] == {"wage", "rent", "gas"}
    r = refs()
    r["census_b25064"]["values"]["35620"] = 1900
    r["eia_html"]["period"] = "Sep-26"
    errs, _ = v.check_references(wages, rent, gas, r)
    assert any("rent 35620" in e for e in errs)
    assert any("reference period" in e for e in errs)


def test_missing_references_is_error():
    wages, rent, gas = sample()
    errs, _ = v.check_references(wages, rent, gas, {})
    assert len(errs) == 3


def test_null_vs_value_mismatch():
    errs, _ = v.compare({"1": None}, {"1": 5.0}, 0.01)
    assert errs


def test_report_rows_completeness_and_hours():
    wages, rent, gas = sample()
    _, checked = v.check_references(wages, rent, gas, refs())
    rows = {r["cbsa"]: r for r in v.report_rows(wages, rent, gas, checked)}
    ny, sj = rows["35620"], rows["41980"]
    assert ny["measures_missing"] == ""
    assert ny["hours_rent_all_units"] == round(1932 / 29.53, 2)
    assert ny["hours_per_gallon"] == round(4.27 / 29.53, 2)
    assert sj["measures_missing"] == "rent_1br;gas"
    assert sj["hours_per_gallon"] is None
    assert sj["gas_as_of"] == ""
    assert sj["name"] == "San Juan-Bayamón"  # ACS name preferred


def test_bls_series_id():
    assert v.bls_series_id("35620") == "OEUM003562000000000000008"
    assert len(v.bls_series_id("10180")) == 25


def test_parse_bls_response():
    payload = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
        {"seriesID": "OEUM003562000000000000008", "data": [{"year": "2025", "period": "A01", "value": "29.53"}]},
        {"seriesID": "OEUM001018000000000000008", "data": []},
        {"seriesID": "OEUM001234500000000000008", "data": [{"year": "2025", "period": "A01", "value": "-"}]},
    ]}}
    assert v.parse_bls_response(payload, "2025") == {"35620": 29.53, "10180": None, "12345": None}


def test_parse_bls_limit_raises():
    import pytest
    with pytest.raises(RuntimeError):
        v.parse_bls_response({"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold"]}, "2025")


def test_parse_eia_html():
    html = ("<tr><th>May-26</th><th>Jun-26</th><th>Jul-26</th><th>Aug-26</th><th>Sep-26</th><th>Oct-26</th></tr>"
            "<tr><td>New York</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1</td><td>4.324</td></tr>"
            "<tr><td>Cities&nbsp;</td></tr>"
            "<tr><td>Boston</td><td>4.4</td><td>4.1</td><td>3.9</td><td>4.0</td><td>4.2</td><td>4.266</td></tr>"
            "<tr><td>New York City</td><td>4.4</td><td>4.0</td><td>3.9</td><td>4.0</td><td>4.3</td><td>4.270</td></tr>"
            "<tr><td>Seattle</td><td>4.4</td><td>4.0</td><td>3.9</td><td>4.0</td><td>4.3</td><td>NA</td></tr>")
    month, vals = v.parse_eia_html(html)
    assert month == "Oct-26"
    assert vals["Boston"] == 4.266
    assert vals["New York City"] == 4.27  # not the state row
    assert vals["Seattle"] is None


def test_structure_requires_tier_and_method():
    wages, rent, gas = sample()
    rent["metros"]["35620"]["all_units"].pop("tier")
    rent["metros"]["35620"]["one_bedroom"]["method"] = "undefined_method"
    rent["metros"]["41980"]["all_units"]["tier"] = "guessed"
    errs = v.check_structure("rent", rent, list(v.RENT_KEYS))
    assert any("35620.all_units: missing or invalid tier" in e for e in errs)
    assert any("not defined in methods table" in e for e in errs)
    assert any("'guessed'" in e for e in errs)


def test_structure_requires_complete_methods_table():
    wages, rent, gas = sample()
    rent["methods"] = {"m": {"description": "", "inputs": [], "as_of": ""}}
    errs = v.check_structure("rent", rent, list(v.RENT_KEYS))
    assert any("missing description" in e for e in errs)
    assert any("missing inputs" in e for e in errs)
    assert any("missing as_of" in e for e in errs)
    del rent["methods"]
    assert any("missing methods table" in e for e in v.check_structure("rent", rent, list(v.RENT_KEYS)))
