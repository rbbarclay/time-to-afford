"""Map geometry: Census state outlines and metro points -> web/data/basemap.json, data/metro_points.json.

Projects everything once, at build time, so the site draws a plain SVG with no
mapping library. Projection: Albers equal-area conic for the lower 48
(parallels 29.5 and 45.5), with Alaska (scaled 0.35), Hawaii and Puerto Rico
moved into insets, as on common U.S. reference maps.

Inputs (U.S. Census Bureau, U.S. government works):
  2025 Gazetteer, CBSA file: internal point (INTPTLAT, INTPTLONG) of each metro
  2024 cartographic boundary file, states, 1:20,000,000 (shapefile)

Usage:
  python pipeline/geo.py                      # download both into data/raw/census_geo/
  python pipeline/geo.py --gazetteer ZIP --states ZIP
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import ssl
import struct
import sys
import urllib.request
import zipfile
from pathlib import Path

import certifi

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "census_geo"
BASEMAP_PATH = ROOT / "web" / "data" / "basemap.json"
POINTS_PATH = ROOT / "data" / "metro_points.json"

GAZETTEER_URL = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/"
                 "2025_Gaz_cbsa_national.zip")
STATES_URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_20m.zip"

WIDTH, HEIGHT = 960, 520
SCALE = 1070  # lower-48 scale, in pixels per radius unit

# Each region: Albers parameters (degrees), the lon/lat placed at `at` (pixels), and a scale factor.
REGIONS = {
    "lower48": {"lon0": -96, "parallels": (29.5, 45.5), "center": (-96.6, 38.7), "at": (480, 250), "k": 1.0},
    "AK": {"lon0": -154, "parallels": (55, 65), "center": (-156, 58.5), "at": (480 - 0.307 * SCALE, 250 + 0.201 * SCALE), "k": 0.35},
    "HI": {"lon0": -157, "parallels": (8, 18), "center": (-157, 19.9), "at": (325, 470), "k": 1.0},
    "PR": {"lon0": -66.5, "parallels": (17, 19), "center": (-66.5, 18.2), "at": (880, 495), "k": 1.6},
}
STATE_REGION = {"02": "AK", "15": "HI", "72": "PR"}


# ---------- projection ----------

def albers(lon: float, lat: float, lon0: float, parallels: tuple[float, float]) -> tuple[float, float]:
    """Spherical Albers equal-area conic, unit radius. y points north."""
    p1, p2 = (math.radians(p) for p in parallels)
    n = (math.sin(p1) + math.sin(p2)) / 2
    c = math.cos(p1) ** 2 + 2 * n * math.sin(p1)
    rho = math.sqrt(c - 2 * n * math.sin(math.radians(lat))) / n
    theta = n * math.radians(lon - lon0)
    return rho * math.sin(theta), -rho * math.cos(theta)


def region_for(lon: float, lat: float) -> str:
    if lat > 50 and (lon < -129 or lon > 170):
        return "AK"
    if lat < 23.5 and lon < -150:
        return "HI"
    if lat < 19 and -68.5 < lon < -65:
        return "PR"
    return "lower48"


def project(lon: float, lat: float, region: str) -> tuple[float, float]:
    """Pixels in a WIDTH x HEIGHT viewBox (y down)."""
    r = REGIONS[region]
    if region == "AK" and lon > 0:
        lon -= 360  # Aleutians west of 180°
    x, y = albers(lon, lat, r["lon0"], r["parallels"])
    cx, cy = albers(*r["center"], r["lon0"], r["parallels"])
    s = SCALE * r["k"]
    return r["at"][0] + s * (x - cx), r["at"][1] - s * (y - cy)


# ---------- reading Census files ----------

def read_gazetteer(path: Path) -> dict:
    """{cbsa: (lon, lat)} from the pipe-delimited Gazetteer CBSA file."""
    with zipfile.ZipFile(path) as zf:
        text = zf.read(zf.namelist()[0]).decode("utf-8-sig")
    lines = text.splitlines()
    header = [h.strip() for h in lines[0].split("|")]
    for col in ("GEOID", "INTPTLAT", "INTPTLONG"):
        if col not in header:
            raise ValueError(f"Gazetteer file has no {col} column")
    out = {}
    for ln in lines[1:]:
        row = dict(zip(header, (c.strip() for c in ln.split("|"))))
        if row.get("GEOID"):
            out[row["GEOID"]] = (float(row["INTPTLONG"]), float(row["INTPTLAT"]))
    return out


def read_dbf(data: bytes) -> list[dict]:
    n_records, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields, pos = [], 32
    while data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\0")[0].decode("ascii")
        fields.append((name, data[pos + 16]))
        pos += 32
    rows = []
    for i in range(n_records):
        rec = data[header_len + i * record_len: header_len + (i + 1) * record_len]
        off, row = 1, {}  # byte 0 is the deletion flag
        for name, length in fields:
            row[name] = rec[off:off + length].decode("utf-8", "replace").strip()
            off += length
        rows.append(row)
    return rows


def read_shp_polygons(data: bytes) -> list[list[list[tuple[float, float]]]]:
    """Each record -> list of rings, each ring a list of (lon, lat). Polygon shapes (type 5) only."""
    shapes, pos = [], 100
    while pos < len(data):
        _, length = struct.unpack(">ii", data[pos:pos + 8])
        content = data[pos + 8: pos + 8 + length * 2]
        pos += 8 + length * 2
        shape_type = struct.unpack("<i", content[:4])[0]
        if shape_type == 0:
            shapes.append([])
            continue
        if shape_type != 5:
            raise ValueError(f"unsupported shape type {shape_type}")
        n_parts, n_points = struct.unpack("<ii", content[36:44])
        parts = list(struct.unpack(f"<{n_parts}i", content[44:44 + 4 * n_parts])) + [n_points]
        base = 44 + 4 * n_parts
        pts = struct.unpack(f"<{2 * n_points}d", content[base:base + 16 * n_points])
        coords = list(zip(pts[0::2], pts[1::2]))
        shapes.append([coords[parts[i]:parts[i + 1]] for i in range(n_parts)])
    return shapes


def read_states(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as zf:
        shp = next(n for n in zf.namelist() if n.endswith(".shp"))
        dbf = next(n for n in zf.namelist() if n.endswith(".dbf"))
        shapes, rows = read_shp_polygons(zf.read(shp)), read_dbf(zf.read(dbf))
    if len(shapes) != len(rows):
        raise ValueError("shapefile and dbf record counts differ")
    return [{"fips": r["STATEFP"], "abbr": r["STUSPS"], "name": r["NAME"], "rings": s} for r, s in zip(rows, shapes)]


# ---------- SVG output ----------

def ring_area(pts: list[tuple[float, float]]) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2


def simplify(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker: drop points within `tol` pixels of the line between kept neighbors."""
    if len(pts) < 4:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = pts[i], pts[j]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        best, idx = 0.0, None
        for k in range(i + 1, j):
            px, py = pts[k]
            d = abs(dy * (px - x1) - dx * (py - y1)) / norm if norm else math.hypot(px - x1, py - y1)
            if d > best:
                best, idx = d, k
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(pts, keep) if k]


def ring_path(pts: list[tuple[float, float]], tol: float = 0.0) -> str:
    out, last = [], None
    for x, y in simplify(pts, tol) if tol else pts:
        p = (round(x, 1), round(y, 1))
        if p != last:
            out.append(p)
            last = p
    if len(out) < 3:
        return ""
    return "M" + "L".join(f"{x:g},{y:g}" for x, y in out) + "Z"


def state_path(state: dict, min_area: float = 1.0, tol: float = 0.4) -> str:
    region = STATE_REGION.get(state["fips"], "lower48")
    parts = []
    for ring in state["rings"]:
        pts = [project(lon, lat, region) for lon, lat in ring]
        if ring_area(pts) >= min_area:
            parts.append(ring_path(pts, tol))
    return "".join(p for p in parts if p)


def inset_boxes(states: list[dict], pad: float = 6) -> list[dict]:
    """Frames around the AK, HI and PR insets, so readers can see they're moved and rescaled."""
    out = []
    for region, label in (("AK", "Alaska (not to scale)"), ("HI", "Hawaii"), ("PR", "Puerto Rico (enlarged)")):
        pts = [project(lon, lat, region) for s in states if STATE_REGION.get(s["fips"]) == region
               for ring in s["rings"] for lon, lat in ring]
        if not pts:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        out.append({"region": region, "label": label,
                    "box": [round(min(xs) - pad, 1), round(min(ys) - pad, 1),
                            round(max(xs) - min(xs) + 2 * pad, 1), round(max(ys) - min(ys) + 2 * pad, 1)]})
    return out


def metro_points(gazetteer: dict, codes) -> dict:
    out = {}
    for code in codes:
        if code not in gazetteer:
            raise ValueError(f"metro {code} not in the Gazetteer")
        lon, lat = gazetteer[code]
        region = region_for(lon, lat)
        x, y = project(lon, lat, region)
        out[code] = {"xy": [round(x, 1), round(y, 1)], "region": region, "lon": lon, "lat": lat}
    return out


def check_points(points: dict) -> list[str]:
    return [f"metro {c} point {p['xy']} outside the {WIDTH}x{HEIGHT} map"
            for c, p in points.items() if not (0 <= p["xy"][0] <= WIDTH and 0 <= p["xy"][1] <= HEIGHT)]


def build_basemap(states: list[dict], retrieved: dt.date) -> dict:
    keep = [s for s in states if s["fips"] <= "56" or s["fips"] == "72"]  # 50 states, DC, Puerto Rico
    return {
        "width": WIDTH, "height": HEIGHT,
        "projection": ("Albers equal-area conic (parallels 29.5° and 45.5°); Alaska scaled 0.35, "
                       "Hawaii and Puerto Rico moved into insets, Puerto Rico enlarged 1.6x"),
        "source": "U.S. Census Bureau, 2024 cartographic boundary file, states, 1:20,000,000",
        "source_url": STATES_URL,
        "retrieved": retrieved.isoformat(),
        "insets": inset_boxes(keep),
        "states": [{"fips": s["fips"], "abbr": s["abbr"], "name": s["name"], "d": state_path(s)}
                   for s in sorted(keep, key=lambda s: s["fips"])],
    }


def download(url: str, dest_dir: Path = RAW_DIR) -> Path:
    dest = dest_dir / url.rsplit("/", 1)[1]
    req = urllib.request.Request(url, headers={"User-Agent": "time-to-afford/0.1"})
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
        data = resp.read()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gazetteer", type=Path, help="local 2025_Gaz_cbsa_national.zip")
    p.add_argument("--states", type=Path, help="local cb_2024_us_state_20m.zip")
    args = p.parse_args(argv)

    gaz_path = args.gazetteer or download(GAZETTEER_URL)
    states_path = args.states or download(STATES_URL)
    retrieved = dt.date.fromtimestamp(states_path.stat().st_mtime) if args.states else dt.date.today()

    codes = json.loads((ROOT / "data" / "wages.json").read_text(encoding="utf-8"))["metros"].keys()
    points = metro_points(read_gazetteer(gaz_path), codes)
    if errors := check_points(points):
        for e in errors:
            print("ERROR", e, file=sys.stderr)
        return 1
    POINTS_PATH.write_text(json.dumps({
        "source": "U.S. Census Bureau, 2025 Gazetteer Files, core based statistical areas (internal points)",
        "source_url": GAZETTEER_URL, "retrieved": retrieved.isoformat(),
        "width": WIDTH, "height": HEIGHT, "points": points}, indent=1) + "\n", encoding="utf-8")

    basemap = build_basemap(read_states(states_path), retrieved)
    BASEMAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASEMAP_PATH.write_text(json.dumps(basemap, separators=(",", ":")) + "\n", encoding="utf-8")
    regions = {}
    for pt in points.values():
        regions[pt["region"]] = regions.get(pt["region"], 0) + 1
    print(f"Wrote {len(points)} metro points {regions} to {POINTS_PATH}")
    print(f"Wrote {len(basemap['states'])} states to {BASEMAP_PATH} ({BASEMAP_PATH.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
