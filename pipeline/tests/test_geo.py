import io
import math
import struct
import zipfile

import pytest

import geo


def test_albers_center_and_orientation():
    r = geo.REGIONS["lower48"]
    x, y = geo.project(*r["center"], "lower48")
    assert (round(x, 6), round(y, 6)) == r["at"]
    nyc, sf = geo.project(-74.0, 40.7, "lower48"), geo.project(-122.4, 37.8, "lower48")
    assert sf[0] < nyc[0]  # west is left
    north, south = geo.project(-96, 48, "lower48"), geo.project(-96, 30, "lower48")
    assert north[1] < south[1]  # north is up (smaller y)


def test_albers_equal_area_property():
    # Equal-area: two 1x1 degree cells at the same latitude project to equal areas.
    def cell(lon, lat):
        pts = [geo.albers(lon + dx, lat + dy, -96, (29.5, 45.5)) for dx, dy in ((0, 0), (1, 0), (1, 1), (0, 1))]
        return geo.ring_area(pts)
    assert math.isclose(cell(-120, 40), cell(-80, 40), rel_tol=1e-3)


@pytest.mark.parametrize("lon, lat, region", [
    (-149.9, 61.2, "AK"), (175.0, 52.0, "AK"), (-157.9, 21.3, "HI"), (-66.1, 18.4, "PR"),
    (-80.2, 25.8, "lower48"), (-122.3, 47.6, "lower48"), (-97.5, 26.0, "lower48"),
])
def test_region_for(lon, lat, region):
    assert geo.region_for(lon, lat) == region


def test_simplify_keeps_corners_and_drops_near_points():
    square = [(0, 0), (5, 0.1), (10, 0), (10, 10), (0, 10)]
    out = geo.simplify(square, 0.5)
    assert (5, 0.1) not in out and (10, 0) in out and out[0] == (0, 0) and out[-1] == (0, 10)


def test_ring_path_rounds_and_dedupes():
    assert geo.ring_path([(0.01, 0.02), (0.04, 0.0), (10, 0), (10, 10)]) == "M0,0L10,0L10,10Z"
    assert geo.ring_path([(0, 0), (0.01, 0)]) == ""


def _shp_polygon(rings):
    pts = [p for r in rings for p in r]
    parts, n = [], 0
    for r in rings:
        parts.append(n)
        n += len(r)
    content = struct.pack("<i4d2i", 5, 0, 0, 0, 0, len(rings), len(pts))
    content += struct.pack(f"<{len(parts)}i", *parts) + struct.pack(f"<{2 * len(pts)}d", *[c for p in pts for c in p])
    return struct.pack(">ii", 1, len(content) // 2) + content


def _dbf(rows, fields):
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(l for _, l in fields)
    out = struct.pack("<B3BIHH20x", 3, 25, 1, 1, len(rows), header_len, record_len)
    for name, length in fields:
        out += name.encode().ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([length]) + b"\0" * 15
    out += b"\x0d"
    for r in rows:
        out += b" " + b"".join(r[n].encode().ljust(l) for n, l in fields)
    return out


def test_read_states_from_zip(tmp_path):
    rings = [[(-100, 40), (-99, 40), (-99, 41), (-100, 40)]]
    shp = b"\0" * 100 + _shp_polygon(rings)
    dbf = _dbf([{"STATEFP": "31", "STUSPS": "NE", "NAME": "Nebraska"}], [("STATEFP", 2), ("STUSPS", 2), ("NAME", 20)])
    z = tmp_path / "states.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("s.shp", shp)
        zf.writestr("s.dbf", dbf)
    states = geo.read_states(z)
    assert states == [{"fips": "31", "abbr": "NE", "name": "Nebraska", "rings": rings}]
    path = geo.state_path(states[0], min_area=0)
    assert path.startswith("M") and path.endswith("Z")


def test_read_gazetteer_and_points(tmp_path):
    z = tmp_path / "gaz.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("g.txt", "CSAFP|GEOID|NAME|INTPTLAT|INTPTLONG\n408|35620|New York|40.735425|-73.80773\n"
                             "|41980|San Juan|18.294453|-66.036844\n")
    gaz = geo.read_gazetteer(z)
    assert gaz["35620"] == (-73.80773, 40.735425)
    pts = geo.metro_points(gaz, ["35620", "41980"])
    assert pts["41980"]["region"] == "PR"
    assert geo.check_points(pts) == []
    with pytest.raises(ValueError, match="99999"):
        geo.metro_points(gaz, ["99999"])
    assert geo.check_points({"x": {"xy": [-5, 10]}})
