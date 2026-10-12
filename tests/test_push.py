import json

import pytest

from conftest import BUCKET, ROOT
from platform_publish import push
from platform_publish.publish import PushRefused


def get(s3, key):
    return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())


def acl_public(s3, key):
    grants = s3.get_object_acl(Bucket=BUCKET, Key=key)["Grants"]
    return any(g["Grantee"].get("URI", "").endswith("AllUsers") and g["Permission"] == "READ" for g in grants)


def do_push(s3, paths, **kw):
    return push(*paths, bucket=BUCKET, s3=s3, root_url=ROOT, **kw)


def test_first_push_registers_static_stac(s3, make_project):
    res = do_push(s3, make_project())
    assert "flood-detection/saintes-2026-02/flood-extent.tif" in res.uploaded
    item = get(s3, "flood-detection/saintes-2026-02/saintes-2026-02.json")
    col = get(s3, "flood-detection/collection.json")
    cat = get(s3, "catalog.json")
    asset = item["assets"]["flood-extent"]
    assert asset["href"] == f"{ROOT}/flood-detection/saintes-2026-02/flood-extent.tif"
    assert asset["proj:code"] == "EPSG:32630" and asset["file:nodata"] == 255
    assert asset["type"].startswith("image/tiff") and asset["file:checksum"].startswith("1220")
    assert asset["brustt:shown"] is True
    assert [c["label"] for c in asset["brustt:categories"]] == ["No flood", "Flooded"]
    assert item["geometry"]["type"] == "Polygon" and len(item["bbox"]) == 4
    assert all(l["href"].startswith(ROOT) for l in item["links"])
    assert any(l["rel"] == "item" and l["href"] == item["links"][0]["href"] for l in col["links"])
    assert any(l["rel"] == "child" and l["href"] == f"{ROOT}/flood-detection/collection.json" for l in cat["links"])


def test_everything_is_public_read(s3, make_project):
    do_push(s3, make_project())
    for key in ["flood-detection/saintes-2026-02/flood-extent.tif", "flood-detection/saintes-2026-02/saintes-2026-02.json",
                "flood-detection/collection.json", "catalog.json"]:
        assert acl_public(s3, key), key


def test_default_root_url(s3, make_project):
    push(*make_project(), bucket=BUCKET, s3=s3)
    item = get(s3, "flood-detection/saintes-2026-02/saintes-2026-02.json")
    assert item["assets"]["flood-extent"]["href"].startswith("https://data.brustt.xyz/")


def test_refuses_invalid_with_no_writes(s3, make_project):
    with pytest.raises(PushRefused):
        do_push(s3, make_project(raster={"cog": False}))
    assert s3.list_objects_v2(Bucket=BUCKET).get("KeyCount") == 0


def test_registration_is_the_last_write(s3, make_project, monkeypatch):
    order = []
    orig = s3.put_object
    monkeypatch.setattr(s3, "put_object", lambda **kw: (order.append(kw["Key"]), orig(**kw))[1])
    do_push(s3, make_project())
    real = [k for k in order if not k.startswith(".")]
    assert real[-2:] == ["flood-detection/collection.json", "catalog.json"]
    assert real.index("flood-detection/saintes-2026-02/flood-extent.tif") < real.index(
        "flood-detection/saintes-2026-02/saintes-2026-02.json") < real.index("flood-detection/collection.json")


def test_failure_before_registration_leaves_nothing_visible(s3, make_project, monkeypatch):
    orig = s3.put_object

    def boom(**kw):
        if kw["Key"].endswith("saintes-2026-02.json"):
            raise RuntimeError("network down")
        return orig(**kw)
    monkeypatch.setattr(s3, "put_object", boom)
    with pytest.raises(RuntimeError):
        do_push(s3, make_project())
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET).get("Contents", [])]
    assert "catalog.json" not in keys and "flood-detection/collection.json" not in keys


def test_rerun_skips_matching_files_and_is_idempotent(s3, make_project):
    paths = make_project()
    do_push(s3, paths, now="2026-03-01T00:00:00Z")
    res = do_push(s3, paths, now="2026-03-02T00:00:00Z")
    assert res.skipped == ["flood-detection/saintes-2026-02/flood-extent.tif"]
    col = get(s3, "flood-detection/collection.json")
    assert len([l for l in col["links"] if l["rel"] == "item"]) == 1
    cat = get(s3, "catalog.json")
    assert len([l for l in cat["links"] if l["rel"] == "child"]) == 1


def test_update_overwrites_same_keys_and_bumps_updated(s3, make_project, tmp_path):
    paths = make_project()
    do_push(s3, paths, now="2026-03-01T00:00:00Z")
    before = s3.head_object(Bucket=BUCKET, Key="flood-detection/saintes-2026-02/flood-extent.tif")["Metadata"]["sha256"]
    from conftest import write_raster
    write_raster(tmp_path / "flood-extent.tif", seed=1)  # recomputed result
    res = do_push(s3, paths, now="2026-03-05T00:00:00Z")
    assert res.skipped == [] and "flood-detection/saintes-2026-02/flood-extent.tif" in res.uploaded
    after = s3.head_object(Bucket=BUCKET, Key="flood-detection/saintes-2026-02/flood-extent.tif")["Metadata"]["sha256"]
    assert before != after
    item = get(s3, "flood-detection/saintes-2026-02/saintes-2026-02.json")
    assert item["properties"]["updated"] == "2026-03-05T00:00:00Z"
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert len(keys) == 4  # no new keys


def test_dry_run_writes_nothing(s3, make_project):
    res = do_push(s3, make_project(), dry_run=True)
    assert res.uploaded and s3.list_objects_v2(Bucket=BUCKET).get("KeyCount") == 0


def test_second_project_added_to_existing_catalog(s3, make_project):
    do_push(s3, make_project())
    do_push(s3, make_project(project_over={"slug": "deforest", "title": "Deforestation"}))
    cat = get(s3, "catalog.json")
    assert len([l for l in cat["links"] if l["rel"] == "child"]) == 2


def test_cli(s3, make_project, capsys):
    from platform_publish.cli import main
    p, e = make_project()
    assert main(["validate", str(p), str(e)]) == 0
    assert main(["push", str(p), str(e), "--dry-run"]) == 0
    assert "would upload" in capsys.readouterr().out


def test_no_credentials_stored(tmp_path):
    import platform_publish, pathlib
    src = "".join(p.read_text() for p in pathlib.Path(platform_publish.__file__).parent.glob("*.py"))
    assert "aws_secret_access_key" not in src and "aws_access_key_id" not in src


def test_continuous_hints_carried_into_item(s3, make_project):
    rgb = {"bands": [1, 2, 3], "ranges": [[-25, 0], [-30, -5], [0, 1]]}
    p, e = make_project(raster={"count": 3, "dtype": "float32", "nodata": -9999.0, "overview": "AVERAGE"},
                        categories=None, rgb=rgb, shown=False)
    do_push(s3, (p, e))
    a = get(s3, "flood-detection/saintes-2026-02/saintes-2026-02.json")["assets"]["flood-extent"]
    assert a["brustt:rgb"] == rgb and a["brustt:shown"] is False and "brustt:categories" not in a
