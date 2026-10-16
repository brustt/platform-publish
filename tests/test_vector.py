import http.server
import json
import threading

import pytest

from conftest import BUCKET, ROOT
from platform_publish import push, validate
from platform_publish.publish import PushRefused, url_reachable


def errs(rep):
    return " | ".join(rep.errors)


def get(s3, key):
    return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())


def do_push(s3, paths, **kw):
    return push(*paths, bucket=BUCKET, s3=s3, root_url=ROOT, **kw)


def public(s3, key):
    grants = s3.get_object_acl(Bucket=BUCKET, Key=key)["Grants"]
    return any(g["Grantee"].get("URI", "").endswith("AllUsers") and g["Permission"] == "READ" for g in grants)


# --- the pair -------------------------------------------------------------------------------------------------

def test_result_raster_plus_auxiliary_vector_validates(make_vector_project):
    rep = validate(*make_vector_project())
    assert rep.ok, rep.errors
    v = next(l for l in rep.layers if l.slug == "buildings")
    asset = v.asset({"slug": "flood-detection", "attribution": "a", "licence": "CC-BY-4.0"}, "saintes-2026-02",
                    "https://x.test", 1)
    assert asset["brustt:vector_layers"] == ["buildings"] and asset["brustt:download"]["proj:code"] == "EPSG:4326"
    assert v.bbox == pytest.approx([-0.6, 45.7, -0.5, 45.8])


def test_pmtiles_missing_from_manifest_is_an_error(make_vector_project):
    rep = validate(*make_vector_project(tiles=None))
    assert not rep.ok and "tiles" in errs(rep)


def test_pmtiles_file_missing_is_an_error(make_vector_project):
    rep = validate(*make_vector_project(write_tiles=False))
    assert "PMTiles file not found" in errs(rep)


def test_geoparquet_file_missing_is_an_error(make_vector_project):
    rep = validate(*make_vector_project(write_parquet=False))
    assert "GeoParquet file not found" in errs(rep)


def test_parquet_without_geo_metadata_is_an_error(make_vector_project):
    rep = validate(*make_vector_project(parquet={"geo": False}))
    assert "not a GeoParquet" in errs(rep)


def test_raster_tiles_are_not_vector_tiles(make_vector_project):
    rep = validate(*make_vector_project(pmtiles={"tile_type": 2}))
    assert "raster tiles" in errs(rep)


def test_tiles_on_a_raster_layer_is_an_error(make_project):
    assert not validate(*make_project(tiles="x.pmtiles")).ok


def test_vector_layer_takes_no_raster_hints(make_vector_project):
    rep = validate(*make_vector_project(colormap={"name": "viridis", "range": [0, 1]}))
    assert not rep.ok


# --- internal layer names ---------------------------------------------------------------------------------------

def test_layer_name_inferred_when_not_declared(make_vector_project, s3):
    paths = make_vector_project(style={"fill_color": "#ff8800"})
    assert validate(*paths).ok
    do_push(s3, paths)
    asset = get(s3, "flood-detection/saintes-2026-02/saintes-2026-02.json")["assets"]["buildings"]
    assert asset["brustt:vector_layers"] == ["buildings"]
    assert asset["brustt:style"] == {"fill_color": "#ff8800", "layer": "buildings"}


def test_declared_name_that_disagrees_is_an_error(make_vector_project):
    rep = validate(*make_vector_project(style={"layer": "roads"}))
    assert "roads" in errs(rep) and "buildings" in errs(rep)


def test_several_internal_layers_need_one_named(make_vector_project):
    rep = validate(*make_vector_project(pmtiles={"layers": ("buildings", "roads")}, style={"opacity": 0.5}))
    assert "style.layer" in errs(rep)
    assert validate(*make_vector_project(pmtiles={"layers": ("buildings", "roads")}, style={"layer": "roads"})).ok


# --- display hints ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("style", [
    {"fill_color": ["get", "height"]},                 # data-driven expression
    {"fill_color": "red"},                             # not a hex colour
    {"opacity": ["interpolate", ["linear"], 1]},
    {"opacity": 1.5},
    {"fill_expression": "height > 3"},                 # no data-driven keys at all
    {"stroke_width": 2},                               # nothing beyond the four hints
])
def test_style_accepts_only_the_four_static_hints(make_vector_project, style):
    assert not validate(*make_vector_project(style=style)).ok


def test_style_is_optional(make_vector_project):
    assert validate(*make_vector_project(style=None)).ok


# --- declared values must agree with the files ----------------------------------------------------------------

@pytest.mark.parametrize("over,needle", [
    ({"crs": "EPSG:3857"}, "crs"),
    ({"bbox": [0, 0, 1, 1]}, "bbox"),
    ({"media_type": "text/csv"}, "media_type"),
    ({"checksum": "0" * 64}, "checksum"),
])
def test_declared_value_disagreeing_with_files(make_vector_project, over, needle):
    assert needle in errs(validate(*make_vector_project(**over)))


def test_nodata_does_not_apply_to_vectors(make_vector_project):
    assert not validate(*make_vector_project(nodata=0)).ok


# --- auxiliary ------------------------------------------------------------------------------------------------

def test_auxiliary_role_accepted(make_vector_project):
    assert validate(*make_vector_project()).ok


@pytest.mark.parametrize("missing", ["attribution", "licence"])
def test_auxiliary_vector_needs_attribution_and_licence(make_vector_project, missing):
    rep = validate(*make_vector_project(source_url=None, **{missing: None}))
    assert f"must carry {missing}" in errs(rep)


@pytest.mark.parametrize("missing", ["attribution", "licence"])
def test_empty_attribution_or_licence_is_an_error(make_vector_project, missing):
    assert not validate(*make_vector_project(**{missing: ""})).ok


# --- OpenStreetMap prefill ------------------------------------------------------------------------------------

def test_osm_source_prefills_attribution_and_licence(make_vector_project, s3):
    paths = make_vector_project(attribution=None, licence=None, licence_url=None)
    rep = validate(*paths)
    assert rep.ok, rep.errors
    assert any("OpenStreetMap" in n for n in rep.notes)
    do_push(s3, paths)
    a = get(s3, "flood-detection/saintes-2026-02/saintes-2026-02.json")["assets"]["buildings"]
    assert a["brustt:attribution"] == "© OpenStreetMap contributors"
    assert a["brustt:licence"] == "ODbL-1.0"
    assert a["brustt:licence_url"] == "https://opendatacommons.org/licenses/odbl/1-0/"


def test_osm_prefill_remains_editable(make_vector_project, s3):
    paths = make_vector_project(attribution="© OSM contributors, via Geofabrik", licence=None, licence_url=None)
    do_push(s3, paths)
    a = get(s3, "flood-detection/saintes-2026-02/saintes-2026-02.json")["assets"]["buildings"]
    assert a["brustt:attribution"] == "© OSM contributors, via Geofabrik"
    assert a["brustt:licence"] == "ODbL-1.0"


def test_no_prefill_for_other_sources(make_vector_project):
    rep = validate(*make_vector_project(source_url="https://example.org/data", attribution=None, licence=None))
    assert not rep.ok and not rep.notes


# --- licence URL reachability: push only ------------------------------------------------------------------------

def test_unreachable_licence_url_fails_push(make_vector_project, s3, monkeypatch):
    monkeypatch.setattr("platform_publish.publish.url_reachable",
                        lambda url, timeout=10.0: "HTTP 404" if "odbl" in url else None)
    paths = make_vector_project()
    with pytest.raises(PushRefused, match="licence URL not reachable.*odbl"):
        do_push(s3, paths)
    assert s3.list_objects_v2(Bucket=BUCKET).get("KeyCount", 0) == 0  # nothing was written


def test_unreachable_project_licence_url_fails_push(make_project, s3, monkeypatch):
    monkeypatch.setattr("platform_publish.publish.url_reachable", lambda url, timeout=10.0: "ConnectionError")
    with pytest.raises(PushRefused, match="licence URL not reachable"):
        do_push(s3, make_project())


def test_validate_works_offline_with_unreachable_licence_url(make_vector_project, monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    assert validate(*make_vector_project(licence_url="https://licence.invalid/x")).ok


@pytest.fixture
def local_server():
    class H(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response({"/ok": 200, "/gone": 404, "/nohead": 405}.get(self.path, 404))
            self.end_headers()

        def do_GET(self):
            self.send_response(200 if self.path in ("/ok", "/nohead") else 404)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_url_reachable_against_a_local_server(local_server):
    assert url_reachable(local_server + "/ok") is None
    assert url_reachable(local_server + "/nohead") is None  # falls back to GET
    assert url_reachable(local_server + "/gone") == "HTTP 404"
    assert url_reachable("http://127.0.0.1:1/") is not None  # connection refused


# --- push -----------------------------------------------------------------------------------------------------

def test_push_uploads_both_files_public_read(s3, make_vector_project):
    res = do_push(s3, make_vector_project())
    base = "flood-detection/saintes-2026-02/"
    assert base + "buildings.parquet" in res.uploaded and base + "buildings.pmtiles" in res.uploaded
    for key in (base + "buildings.parquet", base + "buildings.pmtiles", base + "flood-extent.tif"):
        assert public(s3, key), key
    head = s3.head_object(Bucket=BUCKET, Key=base + "buildings.pmtiles")
    assert head["ContentType"] == "application/vnd.pmtiles" and len(head["Metadata"]["sha256"]) == 64
    assert s3.head_object(Bucket=BUCKET, Key=base + "buildings.parquet")["ContentType"] == "application/vnd.apache.parquet"


def test_item_holds_one_layer_with_two_files(s3, make_vector_project):
    do_push(s3, make_vector_project())
    item = get(s3, "flood-detection/saintes-2026-02/saintes-2026-02.json")
    assert list(item["assets"]) == ["flood-extent", "buildings"]  # one entry per Layer, in draw order
    a = item["assets"]["buildings"]
    assert a["href"] == f"{ROOT}/flood-detection/saintes-2026-02/buildings.pmtiles"
    assert a["brustt:download"]["href"] == f"{ROOT}/flood-detection/saintes-2026-02/buildings.parquet"
    assert a["brustt:download"]["type"] == "application/vnd.apache.parquet"
    assert a["brustt:download"]["file:checksum"].startswith("1220")
    assert a["brustt:role"] == "auxiliary" and a["brustt:kind"] == "vector" and a["brustt:order"] == 1
    assert a["brustt:style"]["fill_color"] == "#ff8800" and a["brustt:style"]["opacity"] == 0.6
    assert a["brustt:source_url"] and a["brustt:licence_url"]
    assert len(item["bbox"]) == 4


def test_rerun_skips_unchanged_vector_files(s3, make_vector_project):
    paths = make_vector_project()
    do_push(s3, paths)
    res = do_push(s3, paths)
    assert {k.rsplit("/", 1)[1] for k in res.skipped} == {"flood-extent.tif", "buildings.parquet", "buildings.pmtiles"}
    assert not [k for k in res.uploaded if not k.endswith(".json")]


def test_changed_pmtiles_is_reuploaded_alone(s3, make_vector_project, tmp_path):
    from conftest import write_pmtiles
    paths = make_vector_project()
    do_push(s3, paths)
    write_pmtiles(tmp_path / "buildings.pmtiles", bounds=(-0.7, 45.7, -0.5, 45.8))
    res = do_push(s3, paths)
    assert [k for k in res.uploaded if k.endswith(".pmtiles")] == ["flood-detection/saintes-2026-02/buildings.pmtiles"]


def test_push_refuses_an_invalid_vector_layer(s3, make_vector_project):
    with pytest.raises(PushRefused):
        do_push(s3, make_vector_project(write_tiles=False))
    assert s3.list_objects_v2(Bucket=BUCKET).get("KeyCount", 0) == 0


def test_dry_run_lists_both_files(s3, make_vector_project):
    res = do_push(s3, make_vector_project(), dry_run=True)
    assert any(k.endswith("buildings.parquet") for k in res.uploaded)
    assert any(k.endswith("buildings.pmtiles") for k in res.uploaded)
    assert s3.list_objects_v2(Bucket=BUCKET).get("KeyCount", 0) == 0


class _Response:
    def __init__(self, status):
        self.status_code = status
        self.headers = {"Access-Control-Allow-Origin": "*"}


def test_post_push_url_check_requests_both_files_of_a_vector_layer(s3, make_vector_project):
    seen = []

    def http_get(url, headers):
        seen.append(url)
        return _Response(206 if "Range" in headers else 200)
    res = do_push(s3, make_vector_project(), verify=True, http_get=http_get)
    base = f"{ROOT}/flood-detection/saintes-2026-02"
    assert res.url_problems == []
    assert f"{base}/buildings.pmtiles" in seen
    assert f"{base}/buildings.parquet" in seen
    assert f"{base}/buildings.tif" not in seen
