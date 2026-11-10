import datetime as dt
import json

import pandas as pd
import pytest

import gas

CODES = list(gas.SERIES_TO_CBSA)


def make_grid(rows, codes=CODES):
    """Mimic EIA sheet layout: title row, code row, name row, then data."""
    n = len(codes)
    return pd.DataFrame(
        [["Back to Contents", "Data 4: Cities"] + [None] * (n - 1),
         ["Sourcekey"] + codes,
         ["Date"] + [f"name {c}" for c in codes]]
        + [[d] + vals for d, vals in rows]
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        (4.2701, {"value": 4.27, "status": "ok"}),
        ("3.5", {"value": 3.5, "status": "ok"}),
        (None, {"value": None, "status": "missing"}),
        (float("nan"), {"value": None, "status": "missing"}),
        ("NA", {"value": None, "status": "missing"}),
        (0, {"value": None, "status": "missing"}),
    ],
)
def test_parse_value(raw, expected):
    assert gas.parse_value(raw) == expected


def test_latest_month_selected():
    grid = make_grid([
        (dt.datetime(2026, 9, 15), [4.0] * 10),
        (dt.datetime(2026, 10, 15), [4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 5.0]),
    ])
    month, metros = gas.extract_latest(grid)
    assert month == dt.date(2026, 10, 1)
    assert len(metros) == 10
    assert metros["14460"]["price_per_gallon"] == {"value": 4.1, "status": "ok",
                                                   "tier": "observed", "method": "eia_gas_14460"}
    assert metros["42660"]["price_per_gallon"]["value"] == 5.0
    assert metros["17410"]["eia_area"] == "Cleveland, OH"


def test_missing_city_value_not_backfilled():
    vals = [4.1] * 10
    vals[2] = None  # Cleveland missing in latest month
    grid = make_grid([(dt.datetime(2026, 9, 15), [4.0] * 10), (dt.datetime(2026, 10, 15), vals)])
    _, metros = gas.extract_latest(grid)
    assert metros["17410"]["price_per_gallon"]["value"] is None
    assert metros["17410"]["price_per_gallon"]["status"] == "missing"
    assert metros["17410"]["price_per_gallon"]["method"] == "eia_gas_17410"


def test_trailing_empty_rows_ignored():
    grid = make_grid([(dt.datetime(2026, 10, 15), [4.1] * 10), (dt.datetime(2026, 11, 15), [None] * 10)])
    month, _ = gas.extract_latest(grid)
    assert month == dt.date(2026, 10, 1)


def test_series_absent_from_file_is_missing():
    grid = make_grid([(dt.datetime(2026, 10, 15), [4.1] * 9)], codes=CODES[:9])
    _, metros = gas.extract_latest(grid)
    assert metros["42660"]["price_per_gallon"]["status"] == "missing"


def test_unknown_layout_raises():
    with pytest.raises(ValueError):
        gas.extract_latest(make_grid([(dt.datetime(2026, 10, 15), [1.0])], codes=["X"]))


def test_find_cities_sheet_and_main(tmp_path):
    path = tmp_path / "eia.xlsx"
    grid = make_grid([(dt.datetime(2026, 10, 15), [4.1] * 10)])
    with pd.ExcelWriter(path) as xw:
        pd.DataFrame([["Contents"]]).to_excel(xw, sheet_name="Contents", header=False, index=False)
        pd.DataFrame([["Back", "Data 1: Retail"], ["k", "x"], ["Date", "y"], [dt.datetime(2026, 10, 15), 4.0]]
                     ).to_excel(xw, sheet_name="Data 1", header=False, index=False)
        grid.to_excel(xw, sheet_name="Data 4", header=False, index=False)
    out = tmp_path / "gas.json"
    assert gas.main(["--file", str(path), "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["as_of"] == "2026-10"
    assert data["reference_period"] == "October 2026 (monthly average)"
    assert data["metros"]["35620"]["price_per_gallon"]["value"] == 4.1


def test_methods_table_one_per_city():
    import tiers
    out = gas.build_output({}, dt.date(2026, 10, 1), dt.date(2026, 11, 8))
    assert len(out["methods"]) == 10
    assert tiers.check_methods("gas", out["methods"]) == []
    m = out["methods"]["eia_gas_35620"]
    assert m["as_of"] == "2026-10"
    assert m["inputs"][0]["series"] == "EMM_EPMR_PTE_Y35NY_DPG" and m["inputs"][0]["sheet"] == "Cities"
