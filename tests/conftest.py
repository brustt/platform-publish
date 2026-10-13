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


@pytest.fixture(autouse=True)
def no_network_licence_check(monkeypatch):
    """push checks licence URLs online; tests never touch the network."""
    monkeypatch.setattr("platform_publish.publish.url_reachable", lambda url, timeout=10.0: None)


def write_pmtiles(path, layers=("buildings",), tile_type=1, bounds=(-0.6, 45.7, -0.5, 45.8)):
    """A minimal PMTiles v3 archive: real header and metadata, no tiles."""
    import gzip
    import json
    import struct
    meta = gzip.compress(json.dumps({"vector_layers": [{"id": n, "fields": {}} for n in layers]}).encode())
    off = 127
    lon0, lat0, lon1, lat1 = (round(v * 1e7) for v in bounds)
    head = struct.pack("<7sB8Q3QBBBBBB4iBii", b"PMTiles", 3, off, 0, off, len(meta), off, 0, off + len(meta), 0,
                       0, 0, 0, 1, 2, 1, tile_type, 0, 14, lon0, lat0, lon1, lat1, 0, 0, 0)
    assert len(head) == 127
    path.write_bytes(head + meta)


def write_geoparquet(path, crs_code=4326, geo=True):
    import json
    import struct
    import pyarrow as pa
    import pyarrow.parquet as pq
    wkb = [struct.pack("<BIdd", 1, 1, -0.55 + i * 0.01, 45.75) for i in range(5)]
    table = pa.table({"id": list(range(5)), "geometry": pa.array(wkb, type=pa.binary())})
    if geo:
        meta = {"version": "1.0.0", "primary_column": "geometry",
                "columns": {"geometry": {"encoding": "WKB", "geometry_types": ["Point"],
                                         "crs": {"id": {"authority": "EPSG", "code": crs_code}}}}}
        table = table.replace_schema_metadata({"geo": json.dumps(meta)})
    pq.write_table(table, path)


OSM_URL = "https://www.openstreetmap.org/copyright"


def vector_layer(**over):
    layer = {"slug": "buildings", "file": "buildings.parquet", "tiles": "buildings.pmtiles", "role": "auxiliary",
             "kind": "vector", "title": "Building footprints", "shown": True,
             "attribution": "© OpenStreetMap contributors", "licence": "ODbL-1.0",
             "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/", "source_url": OSM_URL,
             "style": {"layer": "buildings", "fill_color": "#ff8800", "line_color": "#333333", "opacity": 0.6}}
    layer.update(over)
    return {k: v for k, v in layer.items() if v is not None}


@pytest.fixture
def make_vector_project(tmp_path):
    """A result raster plus one auxiliary vector Layer. Returns (project_yaml, event_yaml)."""
    def _make(pmtiles=None, parquet=None, write_tiles=True, write_parquet=True, **layer_over):
        write_raster(tmp_path / "flood-extent.tif")
        if write_tiles:
            write_pmtiles(tmp_path / "buildings.pmtiles", **(pmtiles or {}))
        if write_parquet:
            write_geoparquet(tmp_path / "buildings.parquet", **(parquet or {}))
        ev = event_doc()
        ev["layers"].append(vector_layer(**layer_over))
        (tmp_path / "project.yaml").write_text(yaml.safe_dump(PROJECT))
        (tmp_path / "saintes-2026-02.publish.yaml").write_text(yaml.safe_dump(ev))
        return tmp_path / "project.yaml", tmp_path / "saintes-2026-02.publish.yaml"
    return _make
