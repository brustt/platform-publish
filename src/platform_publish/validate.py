"""Offline validation of a Project and one Event manifest."""
import math
from dataclasses import dataclass, field
from pathlib import Path

from .manifest import Manifests, load_yaml, schema_errors
from .raster import RasterInfo, inspect


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    manifests: Manifests | None = None
    rasters: dict[str, RasterInfo] = field(default_factory=dict)  # layer slug -> inferred

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(project_yaml: str | Path, event_yaml: str | Path) -> ValidationReport:
    rep = ValidationReport()
    event_yaml = Path(event_yaml)
    try:
        project = load_yaml(Path(project_yaml))
        event = load_yaml(event_yaml)
    except Exception as e:  # unreadable or malformed YAML
        rep.errors.append(f"cannot read manifest: {e}")
        return rep

    rep.errors += [f"project.yaml {m}" for m in schema_errors(project, "project")]
    rep.errors += [f"{event_yaml.name} {m}" for m in schema_errors(event, "event")]
    if rep.errors:
        return rep  # structure must be right before we look at files

    if event["start"] > event["end"]:
        rep.errors.append("event start is after end")
    slugs = [l["slug"] for l in event["layers"]]
    if len(set(slugs)) != len(slugs):
        rep.errors.append("duplicate Layer slugs")
    if not any(l["role"] == "result" for l in event["layers"]):
        rep.errors.append("at least one Layer with role 'result' is required")
    for c in event.get("compare", []):
        if c not in slugs:
            rep.errors.append(f"compare names unknown Layer '{c}'")

    base = event_yaml.parent
    rep.manifests = Manifests(project, event, base)
    for layer in event["layers"]:
        _check_layer(rep, layer, base)
    return rep


def _check_layer(rep: ValidationReport, layer: dict, base: Path) -> None:
    s = layer["slug"]
    err = lambda m: rep.errors.append(f"layer '{s}': {m}")  # noqa: E731
    if layer["role"] == "auxiliary":
        for k in ("licence", "attribution"):
            if not layer.get(k):
                err(f"auxiliary Layers must carry {k}")
    categorical = "categories" in layer
    values = [c["value"] for c in layer.get("categories", [])]
    if len(set(values)) != len(values):
        err("duplicate values in categories")

    path = (base / layer["file"]).resolve()
    if not path.is_file():
        err(f"file not found: {layer['file']}")
        return
    try:
        info = inspect(path, categorical)
    except Exception as e:
        err(f"cannot read raster: {e}")
        return
    rep.rasters[s] = info
    for p in info.problems:
        err(p)
    if info.nodata is None or (isinstance(info.nodata, float) and math.isnan(info.nodata)):
        err("no-data value is not declared in the file")
    if categorical:
        if info.overview_resampling and info.overview_resampling not in ("nearest", "mode"):
            err(f"overviews were built with '{info.overview_resampling}' resampling: "
                "use nearest or mode on a categorical raster")
        known = set(values) | ({info.nodata} if info.nodata is not None else set())
        stray = info.overview_values - known
        if stray:
            err(f"overviews contain values {sorted(stray)} that are not categories: "
                "use nearest or mode resampling")
    if "colormap" in layer and layer["colormap"].get("band", 1) > info.count:
        err(f"colormap band {layer['colormap']['band']} but the file has {info.count} band(s)")
    if "rgb" in layer:
        if max(layer["rgb"]["bands"]) > info.count:
            err(f"rgb bands {layer['rgb']['bands']} but the file has {info.count} band(s)")
    for key in ("colormap", "rgb"):
        for r in ([layer[key]["range"]] if key == "colormap" and key in layer else
                  layer.get(key, {}).get("ranges", [])):
            if r[0] >= r[1]:
                err(f"{key} range {r} must have min < max")
    # a declared value that disagrees with the file is an error
    if "nodata" in layer and info.nodata is not None and layer["nodata"] != info.nodata:
        err(f"declared nodata {layer['nodata']} but file has {info.nodata}")
    if "crs" in layer and layer["crs"].upper() != (info.crs or "").upper():
        err(f"declared crs {layer['crs']} but file has {info.crs}")
    if "media_type" in layer and layer["media_type"] != info.media_type:
        err(f"declared media_type {layer['media_type']} but file is {info.media_type}")
    if "checksum" in layer and layer["checksum"] != info.sha256:
        err("declared checksum does not match the file")
    if "bbox" in layer and any(abs(a - b) > 1e-4 for a, b in zip(layer["bbox"], info.bbox)):
        err(f"declared bbox {layer['bbox']} but file has {[round(x, 6) for x in info.bbox]}")
