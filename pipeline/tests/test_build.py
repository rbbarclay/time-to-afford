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
