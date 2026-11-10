import datetime as dt
import json

import pytest

import owner
import tiers

GEOS = [
    "FILEID|SUMLEVEL|GEO_ID|NAME",
    "ACSSF|310|310M700US35620|New York-Newark-Jersey City, NY-NJ Metro Area",
    "ACSSF|310|310M700US41860|San Francisco-Oakland-Fremont, CA Metro Area",
    "ACSSF|310|310M700US10100|Aberdeen, SD Micro Area",
]
B25077 = [
    "GEO_ID|B25077_E001|B25077_M001",
    "0100000US|350000|900",
    "310M700US35620|691700|5263",
    "310M700US41860|1250000|20000",
    "310M700US10100|200000|9000",
]
B25088 = [
    "GEO_ID|B25088_E001|B25088_M001|B25088_E002|B25088_M002|B25088_E003|B25088_M003",
    "310M700US35620|2554|22|3441|23|1435|11",
    "310M700US41860|3200|40|4001|-555555555|1000|20",
    "310M700US10100|1200|50|1600|60|500|30",
]


def rows():
    return {"home_value": owner.read_pipe(B25077), "owner_cost_with_mortgage": owner.read_pipe(B25088)}


def names():
    return owner.metro_names(owner.read_pipe(GEOS))


def test_extracts_metros_only_with_tier_and_method():
    metros = owner.extract_metros(rows(), names())
    assert list(metros) == ["35620", "41860"]  # national and micropolitan rows dropped
    ny = metros["35620"]
    assert ny["name"] == "New York-Newark-Jersey City, NY-NJ"
    assert ny["home_value"] == {"value": 691700, "moe": 5263, "status": "ok",
                                "tier": "observed", "method": "acs_home_value"}
    assert ny["owner_cost_with_mortgage"] == {"value": 3441, "moe": 23, "status": "ok",
                                              "tier": "observed", "method": "acs_owner_cost_with_mortgage"}


def test_uses_with_mortgage_column_not_total():
    assert owner.extract_metros(rows(), names())["35620"]["owner_cost_with_mortgage"]["value"] == 3441  # not 2554


def test_owner_cost_top_code_not_filled_in():
    sf = owner.extract_metros(rows(), names())["41860"]
    assert sf["owner_cost_with_mortgage"]["status"] == "top_coded"
    assert sf["owner_cost_with_mortgage"]["value"] is None
    assert sf["home_value"]["value"] == 1250000


def test_home_value_top_code():
    r = rows()
    r["home_value"] = owner.read_pipe(["GEO_ID|B25077_E001|B25077_M001", "310M700US35620|2000001|-555555555"])
    ny = owner.extract_metros(r, names())["35620"]
    assert ny["home_value"]["status"] == "top_coded"


def test_metro_absent_from_one_table_is_missing():
    r = rows()
    r["owner_cost_with_mortgage"] = owner.read_pipe(B25088[:2])  # header + New York only
    sf = owner.extract_metros(r, names())["41860"]
    assert sf["owner_cost_with_mortgage"] == {"value": None, "moe": None, "status": "missing",
                                              "tier": "observed", "method": "acs_owner_cost_with_mortgage"}


def test_missing_columns_raise():
    r = rows()
    r["owner_cost_with_mortgage"] = owner.read_pipe(["GEO_ID|B25088_E001", "310M700US35620|2554"])
    with pytest.raises(ValueError, match="B25088_E002"):
        owner.extract_metros(r, names())


def test_methods_table_and_label_says_costs_are_bundled():
    out = owner.build_output(owner.extract_metros(rows(), names()), 2025, dt.date(2026, 11, 8))
    assert tiers.check_methods("owner", out["methods"]) == []
    cost = out["methods"]["acs_owner_cost_with_mortgage"]
    assert "taxes" in cost["description"] and "insurance" in cost["description"]
    assert cost["inputs"][0]["estimate"] == "B25088_E002"
    assert cost["inputs"][0]["url"].endswith("acsdt1y2025-b25088.dat")
    assert cost["as_of"] == "2025"
    assert out["reference_period"] == "2025 (ACS 1-year)"
    for m in out["metros"].values():
        for k in owner.MEASURES:
            assert tiers.check_value(k, m[k], out["methods"]) == []


def test_main_with_local_files(tmp_path):
    files = {}
    for name, lines in [("v.dat", B25077), ("c.dat", B25088), ("g.txt", GEOS)]:
        files[name] = tmp_path / name
        files[name].write_text("\n".join(lines) + "\n")
    out = tmp_path / "owner.json"
    assert owner.main(["--year", "2025", "--value-file", str(files["v.dat"]), "--cost-file", str(files["c.dat"]),
                       "--geos-file", str(files["g.txt"]), "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["metros"]["35620"]["home_value"]["value"] == 691700


def test_local_files_must_come_together(tmp_path):
    with pytest.raises(SystemExit):
        owner.main(["--year", "2025", "--value-file", str(tmp_path / "v.dat")])
