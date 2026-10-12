import boto3
import numpy as np
import pytest
import rasterio
import yaml
from moto import mock_aws
from rasterio.shutil import copy
from rasterio.transform import from_origin

BUCKET = "brustt-test"
ROOT = "https://data.example.test"


def write_raster(path, *, cog=True, overview="NEAREST", nodata=255, crs="EPSG:32630", seed=0, count=1, dtype="uint8"):
    rng = np.random.default_rng(seed)
    if dtype == "float32":  # continuous
        data = rng.normal(-15, 5, size=(count, 512, 512)).astype("float32")
        data[:, :16, :16] = nodata
    else:
        data = rng.choice([0, 10], size=(1, 512, 512), p=[0.6, 0.4]).astype("uint8")
        data[:, :16, :16] = 255
    profile = dict(driver="GTiff", height=512, width=512, count=count, dtype=dtype, crs=crs,
                   transform=from_origin(500000, 5000000, 10, 10), nodata=nodata)
    src = path if not cog else path.with_suffix(".src.tif")
    with rasterio.open(src, "w", **profile) as dst:
        dst.write(data)
    if cog:
        copy(src, path, driver="COG", BLOCKSIZE=256, OVERVIEW_RESAMPLING=overview)


PROJECT = {"slug": "flood-detection", "title": "Flood detection", "description": "Floods from SAR",
           "licence": "CC-BY-4.0", "licence_url": "https://creativecommons.org/licenses/by/4.0/",
           "attribution": "brustt"}


def event_doc(**layer_over):
    layer = {"slug": "flood-extent", "file": "flood-extent.tif", "role": "result", "kind": "raster",
             "title": "Flood extent", "shown": True,
             "categories": [{"value": 0, "color": "#000000", "label": "No flood", "transparent": True},
                            {"value": 10, "color": "#1f78b4", "label": "Flooded"}]}
    layer.update(layer_over)
    layer = {k: v for k, v in layer.items() if v is not None}  # None drops a key
    return {"event": "saintes-2026-02", "title": "Saintes flood", "start": "2026-02-15",
            "end": "2026-02-19", "layers": [layer]}


@pytest.fixture
def make_project(tmp_path):
    """Write manifests + a COG; returns (project_yaml, event_yaml). Keyword overrides tweak the layer."""
    def _make(raster=None, event_over=None, project_over=None, **layer_over):
        write_raster(tmp_path / "flood-extent.tif", **(raster or {}))
        ev = event_doc(**layer_over)
        ev.update(event_over or {})
        pj = {**PROJECT, **(project_over or {})}
        (tmp_path / "project.yaml").write_text(yaml.safe_dump(pj))
        (tmp_path / "saintes-2026-02.publish.yaml").write_text(yaml.safe_dump(ev))
        return tmp_path / "project.yaml", tmp_path / "saintes-2026-02.publish.yaml"
    return _make


@pytest.fixture
def s3():
    with mock_aws():
        c = boto3.client("s3", region_name="us-east-1")
        c.create_bucket(Bucket=BUCKET)
        yield c
