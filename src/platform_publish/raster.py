"""Inspect a GeoTIFF: everything the tooling infers instead of asking the owner."""
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform_bounds, transform


@dataclass
class RasterInfo:
    crs: str | None
    nodata: float | None
    bbox: list[float]  # WGS84 west, south, east, north
    footprint: dict  # GeoJSON polygon, WGS84
    sha256: str
    size: int
    count: int = 1
    media_type: str = "image/tiff; application=geotiff; profile=cloud-optimized"
    problems: list[str] = field(default_factory=list)  # COG / overview problems
    overview_values: set = field(default_factory=set)  # distinct values found in overviews
    base_values: set = field(default_factory=set)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _footprint(src) -> tuple[list[float], dict]:
    crs = src.crs
    west, south, east, north = transform_bounds(crs, "EPSG:4326", *src.bounds, densify_pts=21)
    l, b, r, t = src.bounds
    n = 11  # densify the outline so the polygon follows the projected edge
    xs = list(np.linspace(l, r, n)) + [r] * n + list(np.linspace(r, l, n)) + [l] * n
    ys = [t] * n + list(np.linspace(t, b, n)) + [b] * n + list(np.linspace(b, t, n))
    lon, lat = transform(crs, "EPSG:4326", xs, ys)
    ring = [[round(a, 6), round(c, 6)] for a, c in zip(lon, lat)]
    ring.append(ring[0])
    return [west, south, east, north], {"type": "Polygon", "coordinates": [ring]}


def inspect(path: Path, categorical: bool = True) -> RasterInfo:
    problems: list[str] = []
    with rasterio.open(path) as src:
        if src.driver != "GTiff":
            problems.append(f"not a GeoTIFF (driver {src.driver})")
        if src.crs is None:
            raise ValueError("raster has no CRS")
        bbox, footprint = _footprint(src)
        crs = src.crs.to_string()
        epsg = src.crs.to_epsg()
        if epsg:
            crs = f"EPSG:{epsg}"
        layout = src.tags(ns="IMAGE_STRUCTURE").get("LAYOUT")
        if layout != "COG":
            problems.append("not a valid Cloud-Optimized GeoTIFF (tiled, overviews first, COG layout)")
        ovr = src.overviews(1)
        if not ovr:
            problems.append("no internal overviews")
        if any(Path(f).suffix == ".ovr" for f in src.files):
            problems.append("overviews are external (.ovr), they must be internal")
        base_values: set = set()
        ov_values: set = set()
        if categorical and src.count >= 1:
            base_values = set(np.unique(src.read(1)).tolist())
            for f in ovr:
                a = src.read(1, out_shape=(max(1, src.height // f), max(1, src.width // f)),
                             resampling=rasterio.enums.Resampling.nearest)
                ov_values |= set(np.unique(a).tolist())
        return RasterInfo(
            crs=crs, nodata=src.nodata, count=src.count, bbox=bbox, footprint=footprint,
            sha256=sha256_of(path), size=path.stat().st_size,
            problems=problems, overview_values=ov_values, base_values=base_values,
        )
