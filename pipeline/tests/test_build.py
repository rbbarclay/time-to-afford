import datetime as dt

import build


def ok(x, method="m", **kw):
    return {"value": x, "status": "ok", **kw, "tier": "observed", "method": method}


def meth(desc):
    return {"description": desc, "inputs": [{"source": "test"}], "as_of": "2025"}


def sample():
    wages = {"source": "BLS", "as_of": "2025-05", "reference_period": "May 2025",
             "methods": {"wage_med": meth("median"), "wage_mean": meth("mean"), "emp": meth("employment")},
             "metros": {
        "35620": {"name": "New York", "hourly_median": ok(29.53, "wage_med"), "hourly_mean": ok(41.5, "wage_mean"),
                  "employment": ok(1, "emp")},
        "10180": {"name": "Abilene, TX", "hourly_median": ok(21.32, "wage_med"), "hourly_mean": ok(25, "wage_mean"),
                  "employment": ok(1, "emp")},
    }}
    rent = {"source": "ACS", "as_of": "2025", "measures": {"all_units": "All units", "one_bedroom": "1 bedroom"},
            "default_measure": "all_units", "methods": {"rent_all": meth("all"), "rent_1br": meth("1br")},
            "metros": {
        "35620": {"name": "New York", "all_units": ok(1932, "rent_all", moe=15), "one_bedroom": ok(1774, "rent_1br", moe=22)},
        "10180": {"name": "Abilene, TX", "all_units": ok(1230, "rent_all", moe=66),
                  "one_bedroom": {"value": None, "moe": None, "status": "missing", "tier": "observed", "method": "rent_1br"}},
    }}
    gas = {"source": "EIA", "as_of": "2026-10", "coverage_note": "10 cities", "methods": {"gas_ny": meth("gas")},
           "metros": {"35620": {"eia_area": "New York City", "price_per_gallon": ok(4.27, "gas_ny")}}}
    return wages, rent, gas


def test_bundle_shape_and_order():
    b = build.build_bundle(*sample(), dt.date(2026, 11, 8))
    assert b["built"] == "2026-11-08"
    assert [m["cbsa"] for m in b["metros"]] == ["10180", "35620"]  # sorted by name
    ny = b["metros"][1]
    assert ny["wage_median"] == ok(29.53, "wage_med")
    assert ny["rent"]["all_units"] == ok(1932, "rent_all", moe=15)
    assert ny["gas"] == ok(4.27, "gas_ny")
    assert "hourly_mean" not in ny


def test_gas_not_covered_vs_missing():
    b = build.build_bundle(*sample(), dt.date(2026, 11, 8))
    ab = b["metros"][0]
    assert ab["gas"] == {"value": None, "status": "not_covered"}
    assert ab["rent"]["one_bedroom"]["status"] == "missing"


def test_source_metadata():
    s = build.build_bundle(*sample(), dt.date(2026, 11, 8))["sources"]
    assert s["wage"]["as_of"] == "2025-05" and s["wage"]["measure"] == "hourly_median"
    assert s["rent"]["default_measure"] == "all_units"
    assert s["gas"]["coverage_note"] == "10 cities"


def test_refuses_when_validation_fails(monkeypatch):
    monkeypatch.setattr(build.validate, "main", lambda argv: 1)
    assert build.main([]) == 1


def test_bundle_methods_only_those_used_and_check_passes():
    b = build.build_bundle(*sample(), dt.date(2026, 11, 8))
    assert set(b["methods"]) == {"wage_med", "rent_all", "rent_1br", "gas_ny"}  # mean/employment not in bundle
    assert build.check_bundle(b) == []
    assert "tier" not in b["metros"][0]["gas"]  # not_covered: no source, no tier


def test_check_bundle_catches_untagged_values():
    b = build.build_bundle(*sample(), dt.date(2026, 11, 8))
    b["metros"][1]["rent"]["all_units"].pop("method")
    b["metros"][0]["gas"] = {"value": None, "status": "missing"}  # missing (not not_covered) must be tagged
    errs = build.check_bundle(b)
    assert any("35620.rent.all_units: missing method" in e for e in errs)
    assert any("10180.gas: missing or invalid tier" in e for e in errs)


def test_undefined_method_raises():
    wages, rent, gas = sample()
    wages["metros"]["35620"]["hourly_median"]["method"] = "nope"
    import pytest
    with pytest.raises(ValueError, match="nope"):
        build.build_bundle(wages, rent, gas, dt.date(2026, 11, 8))


def est(x, method):
    return {"value": x, "status": "ok", "tier": "estimated", "method": method}


def extras():
    owner = {"source": "ACS", "as_of": "2025",
             "measures": {"home_value": "Median home value", "owner_cost_with_mortgage": "Owner costs"},
             "methods": {"hv": meth("value"), "oc": meth("cost")},
             "metros": {"35620": {"name": "New York", "home_value": ok(691700, "hv", moe=5263),
                                  "owner_cost_with_mortgage": ok(3441, "oc", moe=23)}}}
    groceries = {"source": "BLS", "as_of": "2026-10", "basket_version": 1,
                 "methods": {"bls_milk": meth("milk")},
                 "items": {"milk": {"label": "Milk", "unit": "gallon", "quantity": 1, "series": "APU0000709112",
                                    **ok(4.101, "bls_milk")}}}
    gm = {"source": "BLS x BEA", "as_of": "2026-10", "rpp_year": 2024,
          "methods": {"rpp": meth("rpp"), "est_milk": meth("est")},
          "metros": {"35620": {"name": "New York", "rpp_goods": ok(110.261, "rpp"),
                               "items": {"milk": est(4.522, "est_milk")}}}}
    return owner, groceries, gm


def test_bundle_with_owner_and_groceries():
    owner, groceries, gm = extras()
    b = build.build_bundle(*sample(), dt.date(2026, 11, 13), owner=owner, groceries=groceries, grocery_metro=gm)
    ab, ny = b["metros"]
    assert ny["owner"]["home_value"]["value"] == 691700 and ny["owner"]["owner_cost_with_mortgage"]["moe"] == 23
    assert ny["groceries"]["milk"] == est(4.522, "est_milk") and ny["rpp_goods"]["value"] == 110.261
    assert ab["owner"]["home_value"] == {"value": None, "status": "not_covered"}
    assert ab["groceries"]["milk"] == {"value": None, "status": "not_covered"} and ab["rpp_goods"]["status"] == "not_covered"
    assert b["basket"] == {"version": 1, "as_of": "2026-10", "items": {"milk": {
        "label": "Milk", "unit": "gallon", "quantity": 1, "national": ok(4.101, "bls_milk")}}}
    assert b["sources"]["grocery_estimates"]["rpp_year"] == 2024 and "measures" in b["sources"]["owner"]
    assert {"hv", "oc", "bls_milk", "rpp", "est_milk"} <= set(b["methods"])
    assert build.check_bundle(b) == []


def test_bundle_grocery_checks():
    import pytest
    owner, groceries, gm = extras()
    with pytest.raises(ValueError, match="together"):
        build.build_bundle(*sample(), dt.date(2026, 11, 13), groceries=groceries)
    gm["as_of"] = "2026-09"
    with pytest.raises(ValueError, match="different national month"):
        build.build_bundle(*sample(), dt.date(2026, 11, 13), groceries=groceries, grocery_metro=gm)
    gm["as_of"] = "2026-10"
    b = build.build_bundle(*sample(), dt.date(2026, 11, 13), groceries=groceries, grocery_metro=gm)
    b["metros"][1]["groceries"]["milk"]["tier"] = "observed"
    assert any("expected estimated" in e for e in build.check_bundle(b))


def test_bundle_map_points():
    import pytest
    pts = {"source": "Gazetteer", "source_url": "u", "width": 960, "height": 520,
           "points": {"35620": {"xy": [797.2, 175.5]}, "10180": {"xy": [400.0, 330.0]}}}
    b = build.build_bundle(*sample(), dt.date(2026, 11, 13), points=pts)
    assert b["metros"][1]["xy"] == [797.2, 175.5]
    assert b["sources"]["map"]["width"] == 960
    del pts["points"]["10180"]
    with pytest.raises(ValueError, match="10180 has no map point"):
        build.build_bundle(*sample(), dt.date(2026, 11, 13), points=pts)


def test_bundle_tfp_reference():
    tfp = {"source": "USDA", "as_of": "2026-10", "reference_period": "October 2026",
           "methods": {"tfp": meth("tfp")}, "reference_family_monthly": ok(1024.6, "tfp")}
    b = build.build_bundle(*sample(), dt.date(2026, 11, 13), tfp=tfp)
    assert b["reference"] == {"tfp_family_monthly": ok(1024.6, "tfp")}
    assert b["sources"]["usda_tfp"]["reference_period"] == "October 2026"
    assert "tfp" in b["methods"] and build.check_bundle(b) == []
    b["reference"]["tfp_family_monthly"].pop("tier")
    assert any("reference.tfp_family_monthly" in e for e in build.check_bundle(b))
