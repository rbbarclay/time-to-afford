import datetime as dt

import build


def ok(x, **kw):
    return {"value": x, "status": "ok", **kw}


def sample():
    wages = {"source": "BLS", "as_of": "2025-05", "reference_period": "May 2025", "metros": {
        "35620": {"name": "New York", "hourly_median": ok(29.53), "hourly_mean": ok(41.5), "employment": ok(1)},
        "10180": {"name": "Abilene, TX", "hourly_median": ok(21.32), "hourly_mean": ok(25), "employment": ok(1)},
    }}
    rent = {"source": "ACS", "as_of": "2025", "measures": {"all_units": "All units", "one_bedroom": "1 bedroom"},
            "default_measure": "all_units", "metros": {
        "35620": {"name": "New York", "all_units": ok(1932, moe=15), "one_bedroom": ok(1774, moe=22)},
        "10180": {"name": "Abilene, TX", "all_units": ok(1230, moe=66),
                  "one_bedroom": {"value": None, "moe": None, "status": "missing"}},
    }}
    gas = {"source": "EIA", "as_of": "2026-10", "coverage_note": "10 cities",
           "metros": {"35620": {"eia_area": "New York City", "price_per_gallon": ok(4.27)}}}
    return wages, rent, gas


def test_bundle_shape_and_order():
    b = build.build_bundle(*sample(), dt.date(2026, 11, 8))
    assert b["built"] == "2026-11-08"
    assert [m["cbsa"] for m in b["metros"]] == ["10180", "35620"]  # sorted by name
    ny = b["metros"][1]
    assert ny["wage_median"] == ok(29.53)
    assert ny["rent"]["all_units"] == ok(1932, moe=15)
    assert ny["gas"] == ok(4.27)
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
