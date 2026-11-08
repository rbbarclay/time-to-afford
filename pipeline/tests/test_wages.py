import datetime as dt
import io
import zipfile

import pandas as pd
import pytest

import wages


def sample_df():
    return pd.DataFrame(
        {
            "AREA": ["12060", "35620", "35620", "99999", "10180"],
            "AREA_TITLE": ["Atlanta-Sandy Springs-Roswell, GA", "New York-Newark-Jersey City, NY-NJ",
                           "New York-Newark-Jersey City, NY-NJ", "Some Nonmetro Area", "Abilene, TX"],
            "AREA_TYPE": [4, 4, 4, 6, "4"],
            "O_CODE": ["00-0000", "00-0000", "11-1011", "00-0000", "00-0000"],
            "H_MEDIAN": ["24.50", 31.2, "#", "18.00", "*"],
            "H_MEAN": ["31.10", "40.05", "#", "20.00", "**"],
            "TOT_EMP": ["2,900,000", 9_500_000, "1,000", "50,000", "~"],
        }
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("24.50", {"value": 24.5, "status": "ok"}),
        (31.2, {"value": 31.2, "status": "ok"}),
        ("2,900,000", {"value": 2900000.0, "status": "ok"}),
        ("#", {"value": None, "status": "top_coded"}),
        ("*", {"value": None, "status": "missing"}),
        ("**", {"value": None, "status": "missing"}),
        ("~", {"value": None, "status": "missing"}),
        ("", {"value": None, "status": "missing"}),
        (None, {"value": None, "status": "missing"}),
        (float("nan"), {"value": None, "status": "missing"}),
    ],
)
def test_parse_value(raw, expected):
    assert wages.parse_value(raw) == expected


def test_extract_keeps_only_msa_all_occupations():
    metros = wages.extract_metros(sample_df())
    assert list(metros) == ["10180", "12060", "35620"]  # nonmetro (type 6) and 11-1011 dropped
    assert metros["12060"]["hourly_median"] == {"value": 24.5, "status": "ok"}
    assert metros["35620"]["employment"] == {"value": 9_500_000.0, "status": "ok"}


def test_missing_values_are_not_imputed():
    m = wages.extract_metros(sample_df())["10180"]
    assert m["hourly_median"] == {"value": None, "status": "missing"}
    assert m["hourly_mean"] == {"value": None, "status": "missing"}
    assert m["employment"] == {"value": None, "status": "missing"}


def test_accepts_legacy_occ_code_column_and_lowercase():
    df = sample_df().rename(columns={"O_CODE": "occ_code", "AREA": "area"})
    assert "12060" in wages.extract_metros(df)


def test_missing_columns_raise():
    with pytest.raises(ValueError, match="H_MEDIAN"):
        wages.extract_metros(sample_df().drop(columns=["H_MEDIAN"]))


def test_read_oews_from_zip(tmp_path):
    xlsx = io.BytesIO()
    sample_df().to_excel(xlsx, index=False)
    zpath = tmp_path / "oesm25ma.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("oesm25ma/MSA_M2025_dl.xlsx", xlsx.getvalue())
        zf.writestr("oesm25ma/field_descriptions.xlsx", b"ignored")
    metros = wages.extract_metros(wages.read_oews(zpath))
    assert metros["12060"]["hourly_median"]["value"] == 24.5
    assert wages.year_from_name(zpath) == 2025


def test_build_output_shape():
    out = wages.build_output({"12060": {}}, 2025, dt.date(2026, 11, 8), "http://x")
    assert out["reference_period"] == "May 2025"
    assert out["as_of"] == "2025-05"
    assert out["retrieved"] == "2026-11-08"
    assert out["metros"] == {"12060": {}}


def test_download_requires_contact(monkeypatch):
    monkeypatch.delenv("BLS_CONTACT", raising=False)
    with pytest.raises(SystemExit):
        wages.main([])
