import datetime as dt

import pytest

import rent

GEOS = [
    "FILEID|SUMLEVEL|GEO_ID|NAME",
    "ACSSF|310|310M700US35620|New York-Newark-Jersey City, NY-NJ Metro Area",
    "ACSSF|310|310M700US10100|Aberdeen, SD Micro Area",
    "ACSSF|310|310M700US10180|Abilene, TX Metro Area",
    "ACSSF|010|0100000US|United States",
]
HEADER = "GEO_ID|" + "|".join(f"B25031_{t}{i:03d}" for i in range(1, 8) for t in "EM")
DATA = [
    HEADER,
    "0100000US|1557|4|1|1|1|1|1|1|1|1|1|1|1|1",
    "310M700US35620|1932|15|1683|40|1774|22|1997|26|2270|37|2601|104|2741|151",
    "310M700US10100|900|50|1|1|1|1|1|1|1|1|1|1|1|1",
    "310M700US10180|1230|66|-666666666|-222222222|3501|-555555555|1300|40|1|1|1|1|1|1",
    "312M700US356203436000|2292|93|1|1|1|1|1|1|1|1|1|1|1|1",
]


@pytest.mark.parametrize(
    "est, moe, expected",
    [
        ("1932", "15", {"value": 1932, "moe": 15, "status": "ok"}),
        ("1932", "-555555555", {"value": 1932, "moe": None, "status": "ok"}),
        ("-666666666", "-222222222", {"value": None, "moe": None, "status": "missing"}),
        ("3501", "-555555555", {"value": None, "moe": None, "status": "top_coded"}),
        ("", "", {"value": None, "moe": None, "status": "missing"}),
        (None, None, {"value": None, "moe": None, "status": "missing"}),
    ],
)
def test_parse_estimate(est, moe, expected):
    assert rent.parse_estimate(est, moe) == expected


def test_metro_names_keeps_metros_only_and_strips_suffix():
    names = rent.metro_names(rent.read_pipe(GEOS))
    assert names == {"35620": "New York-Newark-Jersey City, NY-NJ", "10180": "Abilene, TX"}


def test_extract_metros():
    names = rent.metro_names(rent.read_pipe(GEOS))
    metros = rent.extract_metros(rent.read_pipe(DATA), names)
    assert list(metros) == ["10180", "35620"]  # micro, national, and principal-city rows dropped
    ny = metros["35620"]
    assert ny["all_units"] == {"value": 1932, "moe": 15, "status": "ok"}
    assert ny["one_bedroom"]["value"] == 1774
    assert ny["two_bedroom"]["value"] == 1997


def test_missing_and_top_coded_not_imputed():
    names = rent.metro_names(rent.read_pipe(GEOS))
    ab = rent.extract_metros(rent.read_pipe(DATA), names)["10180"]
    assert ab["one_bedroom"] == {"value": None, "moe": None, "status": "top_coded"}
    assert ab["two_bedroom"] == {"value": 1300, "moe": 40, "status": "ok"}


def test_missing_columns_raise():
    bad = ["GEO_ID|B25031_E001", "310M700US35620|1932"]
    with pytest.raises(ValueError, match="B25031_M001"):
        rent.extract_metros(rent.read_pipe(bad), {"35620": "NY"})


def test_build_output_shape():
    out = rent.build_output({"35620": {}}, 2025, dt.date(2026, 11, 8))
    assert out["reference_period"] == "2025 (ACS 1-year)"
    assert out["as_of"] == "2025"
    assert out["default_measure"] == "all_units"
    assert set(out["measures"]) == {"all_units", "one_bedroom", "two_bedroom"}
    assert out["source_url"].endswith("acsdt1y2025-b25031.dat")


def test_local_files_require_year_and_geos(tmp_path):
    with pytest.raises(SystemExit):
        rent.main(["--file", str(tmp_path / "x.dat")])


def test_main_with_local_files(tmp_path):
    d, g, out = tmp_path / "d.dat", tmp_path / "g.txt", tmp_path / "rent.json"
    d.write_text("\n".join(DATA) + "\n")
    g.write_text("\n".join(GEOS) + "\n")
    assert rent.main(["--file", str(d), "--geos-file", str(g), "--year", "2025", "--out", str(out)]) == 0
    import json
    assert json.loads(out.read_text())["metros"]["35620"]["all_units"]["value"] == 1932


def test_utf8_names_decoded(tmp_path):
    g = tmp_path / "g.txt"
    g.write_bytes("GEO_ID|NAME\n310M700US41980|San Juan-Bayam\u00f3n-Caguas, PR Metro Area\n".encode("utf-8"))
    names = rent.metro_names(rent.read_pipe(rent.read_text_lines(g)))
    assert names["41980"] == "San Juan-Bayam\u00f3n-Caguas, PR"
