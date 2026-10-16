"""A Layer of an Event: a manifest entry plus its files on disk, checked and turned into a STAC asset.

``load_layer`` is the only way in. It inspects the files and returns a Layer whose ``errors`` list holds every
problem found. ``bbox``, ``footprint``, ``files`` and ``asset`` are only meaningful when ``errors`` is empty.

Two adapters sit behind it: a raster Layer (one COG) and a vector Layer (a GeoParquet plus a PMTiles).
"""
import math
from datetime import date
from pathlib import Path
from typing import NamedTuple, Protocol

from . import licence
from .raster import inspect
from .stac import layer_key, url
from .vector import inspect_vector

BBOX_TOLERANCE = 1e-4


class LayerFile(NamedTuple):
    key: str  # bucket key
    path: Path
    sha256: str
    content_type: str


class Layer(Protocol):
    slug: str
    errors: list[str]
    bbox: list[float] | None  # WGS84 west, south, east, north
    footprint: dict | None  # GeoJSON polygon, WGS84

    def files(self, project_slug: str, event_slug: str) -> list[LayerFile]: ...

    def asset(self, project: dict, event_slug: str, root: str, order: int) -> dict: ...


def load_layer(layer: dict, base: Path) -> Layer:
    """Inspect one manifest Layer. `base` is the directory its file paths are relative to."""
    return (_VectorLayer if layer["kind"] == "vector" else _RasterLayer)(layer, base)


# --- checks and asset properties shared by both kinds ---------------------------------------------------------

def _check_common(layer: dict, err) -> None:
    if layer["role"] == "auxiliary":
        for k in ("licence", "attribution"):
            if not layer.get(k):
                err(f"auxiliary Layers must carry {k}")
    if "licence" in layer and not licence.is_valid(layer["licence"]):
        err(licence.problem(layer["licence"]))


def _check_declared(layer: dict, inferred: dict, err) -> None:
    """A value the owner declared that disagrees with the files is an error.

    `inferred` maps crs / media_type / checksum / bbox to (value, what was inspected)."""
    for key, (actual, what) in inferred.items():
        if key not in layer or actual is None:
            continue
        declared = layer[key]
        if key == "crs":
            bad = declared.upper() != actual.upper()
        elif key == "bbox":
            bad = any(abs(a - b) > BBOX_TOLERANCE for a, b in zip(declared, actual))
            actual = [round(x, 6) for x in actual]
        else:
            bad = declared != actual
        if bad and key == "checksum":
            err(f"declared checksum does not match {what}")
        elif bad:
            err(f"declared {key} {declared} but {what} has {actual}")


def _common_asset(layer: dict, project: dict, order: int) -> dict:
    a = {
        "title": layer["title"],
        "roles": ["data", layer["role"]],
        "brustt:role": layer["role"],
        "brustt:kind": layer["kind"],
        "brustt:order": order,
        "brustt:shown": layer.get("shown", True),
        "brustt:attribution": layer.get("attribution", project["attribution"]),
        "brustt:licence": layer.get("licence", project["licence"]),
    }
    for hint in ("categories", "colormap", "rgb"):
        if hint in layer:
            a[f"brustt:{hint}"] = layer[hint]
    for src, dst in (("licence_url", "brustt:licence_url"), ("source_url", "brustt:source_url"),
                     ("acquired", "brustt:acquired")):
        if layer.get(src):
            a[dst] = layer[src]
    if "licence_url" not in layer and "licence" not in layer and project.get("licence_url"):
        a["brustt:licence_url"] = project["licence_url"]
    return a


# --- raster adapter -------------------------------------------------------------------------------------------

def _same_nodata(a, b) -> bool:
    return a == b or (isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b))


class _RasterLayer:
    def __init__(self, layer: dict, base: Path):
        self.slug = layer["slug"]
        self.errors: list[str] = []
        self.bbox = self.footprint = None
        self._layer = layer
        self._info = None
        self._path = (base / layer["file"]).resolve()
        err = lambda m: self.errors.append(f"layer '{self.slug}': {m}")  # noqa: E731
        _check_common(layer, err)
        categorical = "categories" in layer
        values = [c["value"] for c in layer.get("categories", [])]
        if len(set(values)) != len(values):
            err("duplicate values in categories")
        if not self._path.is_file():
            err(f"file not found: {layer['file']}")
            return
        try:
            info = inspect(self._path, categorical)
        except Exception as e:
            err(f"cannot read raster: {e}")
            return
        self._info, self.bbox, self.footprint = info, info.bbox, info.footprint
        for p in info.problems:
            err(p)
        if info.nodata is None or (isinstance(info.nodata, float) and math.isnan(info.nodata)):
            err("no-data value is not declared in the file")
        if categorical:
            self._check_overviews(info, values, err)
        self._check_bands(layer, info, err)
        if "acquired" in layer:
            try:
                date.fromisoformat(layer["acquired"])
            except ValueError:
                err(f"acquired '{layer['acquired']}' is not a real date (use YYYY-MM-DD)")
        if "nodata" in layer and info.nodata is not None and not _same_nodata(layer["nodata"], info.nodata):
            err(f"declared nodata {layer['nodata']} but file has {info.nodata}")
        _check_declared(layer, {"crs": (info.crs, "file"), "media_type": (info.media_type, "file"),
                                "checksum": (info.sha256, "the file"), "bbox": (info.bbox, "file")}, err)

    @staticmethod
    def _check_overviews(info, values, err) -> None:
        if info.overview_resampling and info.overview_resampling not in ("nearest", "mode"):
            err(f"overviews were built with '{info.overview_resampling}' resampling: "
                "use nearest or mode on a categorical raster")
        known = set(values) | ({info.nodata} if info.nodata is not None else set())
        stray = info.overview_values - known
        if stray:
            err(f"overviews contain values {sorted(stray)} that are not categories: "
                "use nearest or mode resampling")

    @staticmethod
    def _check_bands(layer, info, err) -> None:
        if "colormap" in layer and layer["colormap"].get("band", 1) > info.count:
            err(f"colormap band {layer['colormap']['band']} but the file has {info.count} band(s)")
        if "rgb" in layer:
            if len(set(layer["rgb"]["bands"])) != 3:
                err(f"rgb bands {layer['rgb']['bands']} must be three different bands")
            if max(layer["rgb"]["bands"]) > info.count:
                err(f"rgb bands {layer['rgb']['bands']} but the file has {info.count} band(s)")
        for key in ("colormap", "rgb"):
            for r in ([layer[key]["range"]] if key == "colormap" and key in layer else
                      layer.get(key, {}).get("ranges", [])):
                if r[0] >= r[1]:
                    err(f"{key} range {r} must have min < max")

    def files(self, project_slug, event_slug):
        return [LayerFile(layer_key(project_slug, event_slug, self.slug), self._path, self._info.sha256, "image/tiff")]

    def asset(self, project, event_slug, root, order):
        info = self._info
        a = {
            "href": url(root, layer_key(project["slug"], event_slug, self.slug)),
            "type": info.media_type,
            "file:checksum": "1220" + info.sha256,
            "file:size": info.size,
            "proj:code": info.crs,
            "file:nodata": info.nodata,
        }
        return a | _common_asset(self._layer, project, order)


# --- vector adapter -------------------------------------------------------------------------------------------

class _VectorLayer:
    """A vector Layer is a GeoParquet (`file`) plus a PMTiles (`tiles`), always both."""

    def __init__(self, layer: dict, base: Path):
        self.slug = layer["slug"]
        self.errors: list[str] = []
        self.bbox = self.footprint = None
        self._layer = layer
        self._info = None
        self._paths = {k: (base / layer[k]).resolve() for k in ("file", "tiles")}
        err = lambda m: self.errors.append(f"layer '{self.slug}': {m}")  # noqa: E731
        _check_common(layer, err)
        for key, what in (("file", "GeoParquet"), ("tiles", "PMTiles")):
            if not self._paths[key].is_file():
                err(f"{what} file not found: {layer[key]} (a vector Layer needs both a GeoParquet and a PMTiles file)")
        if not all(p.is_file() for p in self._paths.values()):
            return
        try:
            info = inspect_vector(self._paths["file"], self._paths["tiles"])
        except Exception as e:
            err(f"cannot read vector files: {e}")
            return
        self._info, self.bbox, self.footprint = info, info.bbox, info.footprint
        for p in info.problems:
            err(p)
        declared = layer.get("style", {}).get("layer")
        if declared is not None:
            if info.layer_names and declared not in info.layer_names:
                err(f"declared vector layer name '{declared}' but the PMTiles contain {info.layer_names}")
        elif len(info.layer_names) > 1:
            err(f"the PMTiles contain several vector layers {info.layer_names}: name one in style.layer")
        _check_declared(layer, {"crs": (info.crs, "the GeoParquet"), "media_type": (info.parquet_type, "the GeoParquet"),
                                "checksum": (info.parquet_sha256, "the GeoParquet file"),
                                "bbox": (info.bbox, "the PMTiles")}, err)

    def files(self, project_slug, event_slug):
        i = self._info
        return [
            LayerFile(layer_key(project_slug, event_slug, self.slug, "parquet"), self._paths["file"],
                      i.parquet_sha256, i.parquet_type),
            LayerFile(layer_key(project_slug, event_slug, self.slug, "pmtiles"), self._paths["tiles"],
                      i.pmtiles_sha256, i.pmtiles_type),
        ]

    def asset(self, project, event_slug, root, order):
        """One asset: PMTiles to display, with the GeoParquet as its download."""
        info, p = self._info, project["slug"]
        style = dict(self._layer.get("style", {}))
        if "layer" not in style and info.layer_names:
            style["layer"] = info.layer_names[0]  # validated: exactly one when not declared
        a = {
            "href": url(root, layer_key(p, event_slug, self.slug, "pmtiles")),
            "type": info.pmtiles_type,
            "file:checksum": "1220" + info.pmtiles_sha256,
            "file:size": info.pmtiles_size,
            "brustt:download": {
                "href": url(root, layer_key(p, event_slug, self.slug, "parquet")),
                "type": info.parquet_type,
                "file:checksum": "1220" + info.parquet_sha256,
                "file:size": info.parquet_size,
                "proj:code": info.crs,
            },
            "brustt:vector_layers": info.layer_names,
        }
        if style:
            a["brustt:style"] = style
        return a | _common_asset(self._layer, project, order)
