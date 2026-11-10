import pytest

import tiers


def test_tag_adds_fields_and_rejects_unknown_tier():
    assert tiers.tag({"value": 1, "status": "ok"}, "estimated", "x") == {
        "value": 1, "status": "ok", "tier": "estimated", "method": "x"}
    with pytest.raises(ValueError):
        tiers.tag({"value": 1, "status": "ok"}, "guess", "x")


def test_method_entry_with_assumptions():
    m = tiers.method_entry("payment", [{"source": "a"}], "2026-11", {"down_payment": 0.2, "term_years": 30})
    assert m["assumptions"] == {"down_payment": 0.2, "term_years": 30}
    assert tiers.check_methods("t", {"k": m}) == []


def test_check_value():
    methods = {"k": tiers.method_entry("d", [{"source": "a"}], "2025")}
    assert tiers.check_value("w", {"value": 1, "status": "ok", "tier": "scenario", "method": "k"}, methods) == []
    assert tiers.check_value("w", {"value": None, "status": "not_covered"}, methods,
                             allow_untagged_status=("not_covered",)) == []
    assert tiers.check_value("w", {"value": None, "status": "not_covered"}, methods)  # not allowed by default
    assert tiers.check_value("w", {"value": 1, "status": "ok", "tier": "observed"}, methods)  # no method
