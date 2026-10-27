"""The Atlas basemap: Natural Earth land, lakes, rivers and region names, clipped to the Near
East and simplified into one small JSON file the review app draws itself (no tile server)."""

from __future__ import annotations

import json
from pathlib import Path

from urim.compiler.ingest.fetch import SOURCES, Fetcher

BBOX = (22.0, 18.0, 52.0, 42.0)  # lon_min, lat_min, lon_max, lat_max: Nile to Persia
TOLERANCE = 0.004  # degrees, about 400 m
DECIMALS = 3

Ring = list[tuple[float, float]]


def clip_ring(ring: Ring, bbox=BBOX) -> Ring:
    """Sutherland-Hodgman against the bbox rectangle."""
    x0, y0, x1, y1 = bbox
    edges = [
        (lambda p: p[0] >= x0, lambda a, b: _cross_x(a, b, x0)),
        (lambda p: p[0] <= x1, lambda a, b: _cross_x(a, b, x1)),
        (lambda p: p[1] >= y0, lambda a, b: _cross_y(a, b, y0)),
        (lambda p: p[1] <= y1, lambda a, b: _cross_y(a, b, y1)),
    ]
    out = ring
    for inside, cross in edges:
        if not out:
            break
        src, out = out, []
        prev = src[-1]
        for cur in src:
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
            prev = cur
    return out


def _cross_x(a, b, x):
    t = (x - a[0]) / (b[0] - a[0])
    return (x, a[1] + t * (b[1] - a[1]))


def _cross_y(a, b, y):
    t = (y - a[1]) / (b[1] - a[1])
    return (a[0] + t * (b[0] - a[0]), y)


def clip_line(line: Ring, bbox=BBOX) -> list[Ring]:
    """Keep the runs of a polyline that fall inside the bbox (vertex test, good enough here)."""
    x0, y0, x1, y1 = bbox
    runs, cur = [], []
    for p in line:
        if x0 <= p[0] <= x1 and y0 <= p[1] <= y1:
            cur.append(p)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return [r for r in runs if len(r) >= 2]


def simplify(points: Ring, tolerance: float = TOLERANCE) -> Ring:
    """Douglas-Peucker, iterative."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        norm = (dx * dx + dy * dy) ** 0.5
        best, idx = 0.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            if norm < 1e-12:  # closed ring: the chord is a point
                d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                d = abs(dy * px - dx * py + bx * ay - by * ax) / norm
            if d > best:
                best, idx = d, i
        if best > tolerance and idx > 0:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep, strict=True) if k]


def _round(points: Ring) -> list[list[float]]:
    return [[round(x, DECIMALS), round(y, DECIMALS)] for x, y in points]


def _polygons(geometry: dict) -> list[list[Ring]]:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    return []


def _lines(geometry: dict) -> list[Ring]:
    if geometry["type"] == "LineString":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiLineString":
        return geometry["coordinates"]
    return []


def _touches(ring: Ring, bbox=BBOX) -> bool:
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return not (max(xs) < bbox[0] or min(xs) > bbox[2] or max(ys) < bbox[1] or min(ys) > bbox[3])


def _area_centroid(ring: Ring) -> tuple[float, float, float]:
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        f = x1 * y2 - x2 * y1
        a += f
        cx += (x1 + x2) * f
        cy += (y1 + y2) * f
    if abs(a) < 1e-12:
        return 0.0, ring[0][0], ring[0][1]
    return abs(a) / 2, cx / (3 * a), cy / (3 * a)


def _polygon_layer(path: Path, keep_props=()) -> list[dict]:
    out = []
    for f in json.loads(path.read_text())["features"]:
        props = f.get("properties") or {}
        for poly in _polygons(f["geometry"]):
            rings = []
            for ring in poly:
                ring = [tuple(p[:2]) for p in ring]
                if not _touches(ring):
                    continue
                clipped = simplify(clip_ring(ring))
                if len(clipped) >= 4:
                    rings.append(_round(clipped))
            if rings:
                out.append({"rings": rings, **{k: props.get(k) for k in keep_props}})
    return out


def build_basemap(fetcher: Fetcher, out: Path) -> dict[str, int]:
    get = lambda name: fetcher.get(SOURCES[f"naturalearth/{name}"])  # noqa: E731
    land = _polygon_layer(get("ne_10m_land"))
    lakes = [x for x in _polygon_layer(get("ne_10m_lakes"), ("name", "scalerank"))]
    rivers = []
    for f in json.loads(get("ne_10m_rivers_lake_centerlines").read_text())["features"]:
        props = f.get("properties") or {}
        for line in _lines(f["geometry"]):
            for run in clip_line([tuple(p[:2]) for p in line]):
                rivers.append(
                    {
                        "name": props.get("name"),
                        "scalerank": props.get("scalerank"),
                        "line": _round(simplify(run)),
                    }
                )
    regions = []
    for f in json.loads(get("ne_10m_geography_regions_polys").read_text())["features"]:
        props = f.get("properties") or {}
        polys = _polygons(f["geometry"])
        if not polys:
            continue
        area, lon, lat = max(_area_centroid([tuple(p[:2]) for p in poly[0]]) for poly in polys)
        x0, y0, x1, y1 = BBOX
        name = props.get("LABEL") or props.get("NAME")
        if x0 <= lon <= x1 and y0 <= lat <= y1 and name:
            regions.append(
                {
                    "name": name,
                    "name_ru": props.get("NAME_RU"),
                    "name_he": props.get("NAME_HE"),
                    "kind": props.get("FEATURECLA"),
                    "scalerank": props.get("SCALERANK"),
                    "min_zoom": props.get("MIN_LABEL"),
                    "lon": round(lon, 2),
                    "lat": round(lat, 2),
                }
            )
    doc = {
        "bbox": BBOX,
        "attribution": "Natural Earth (public domain)",
        "land": land,
        "lakes": lakes,
        "rivers": rivers,
        "regions": regions,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, separators=(",", ":")))
    return {
        "land": len(land),
        "lakes": len(lakes),
        "rivers": len(rivers),
        "regions": len(regions),
        "bytes": out.stat().st_size,
    }
