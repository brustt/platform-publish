"""Inspect a vector Layer's file pair: everything inferred from the GeoParquet and the PMTiles."""
import gzip
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .raster import sha256_of

PARQUET_TYPE = "application/vnd.apache.parquet"
PMTILES_TYPE = "application/vnd.pmtiles"

_MVT = 1  # PMTiles tile type for Mapbox Vector Tiles
_HEADER_LEN = 127


@dataclass
class VectorInfo:
    bbox: list[float]  # WGS84 west, south, east, north, from the PMTiles header
    footprint: dict  # GeoJSON polygon of bbox
    crs: str | None  # CRS of the GeoParquet geometry
    layer_names: list[str]  # internal vector layer names, from the PMTiles metadata
    parquet_sha256: str
    parquet_size: int
    pmtiles_sha256: str
    pmtiles_size: int
    parquet_type: str = PARQUET_TYPE
    pmtiles_type: str = PMTILES_TYPE
    problems: list[str] = field(default_factory=list)


def _bbox_polygon(b):
    w, s, e, n = b
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def read_pmtiles(path: Path) -> tuple[list[float], list[str], list[str]]:
    """Return (bbox, internal layer names, problems) from a PMTiles v3 header and metadata."""
    problems: list[str] = []
    with open(path, "rb") as f:
        head = f.read(_HEADER_LEN)
        if len(head) < _HEADER_LEN or head[:7] != b"PMTiles":
            raise ValueError("not a PMTiles archive")
        if head[7] != 3:
            raise ValueError(f"unsupported PMTiles version {head[7]} (need 3)")
        meta_off, meta_len = struct.unpack_from("<QQ", head, 24)
        internal_compression, tile_type = head[97], head[99]
        min_lon, min_lat, max_lon, max_lat = (v / 1e7 for v in struct.unpack_from("<iiii", head, 102))
        f.seek(meta_off)
        raw = f.read(meta_len)
    if tile_type != _MVT:
        problems.append("PMTiles hold raster tiles: a vector Layer needs vector (MVT) tiles")
    if internal_compression == 2:
        raw = gzip.decompress(raw)
    elif internal_compression not in (0, 1):
        raise ValueError(f"unsupported PMTiles internal compression {internal_compression}")
    meta = json.loads(raw) if raw else {}
    names = [l["id"] for l in meta.get("vector_layers", []) if "id" in l]
    if not names and tile_type == _MVT:
        problems.append("PMTiles metadata has no vector_layers: cannot infer the internal layer names")
    return [min_lon, min_lat, max_lon, max_lat], names, problems


def read_geoparquet_crs(path: Path) -> tuple[str | None, list[str]]:
    """Return (CRS, problems). Needs the GeoParquet 'geo' metadata and a geometry column."""
    import pyarrow.parquet as pq

    schema = pq.read_schema(path)
    raw = (schema.metadata or {}).get(b"geo")
    if raw is None:
        return None, ["not a GeoParquet file: no 'geo' metadata"]
    geo = json.loads(raw)
    col = geo.get("primary_column")
    cols = geo.get("columns", {})
    if col not in cols or col not in schema.names:
        return None, ["GeoParquet 'geo' metadata does not name an existing geometry column"]
    crs = cols[col].get("crs")
    if crs is None:
        return "OGC:CRS84", []  # GeoParquet default when absent
    ident = crs.get("id") if isinstance(crs, dict) else None
    if ident:
        return f"{ident['authority']}:{ident['code']}", []
    return None, []


def inspect_vector(parquet: Path, pmtiles: Path) -> VectorInfo:
    problems: list[str] = []
    bbox, names, tile_problems = read_pmtiles(pmtiles)
    problems += tile_problems
    try:
        crs, crs_problems = read_geoparquet_crs(parquet)
    except Exception as e:
        crs, crs_problems = None, [f"cannot read GeoParquet: {e}"]
    problems += crs_problems
    return VectorInfo(
        bbox=bbox, footprint=_bbox_polygon(bbox), crs=crs, layer_names=names,
        parquet_sha256=sha256_of(parquet), parquet_size=parquet.stat().st_size,
        pmtiles_sha256=sha256_of(pmtiles), pmtiles_size=pmtiles.stat().st_size,
        problems=problems,
    )
