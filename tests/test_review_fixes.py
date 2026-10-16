"""Regression tests for the push/withdraw risks found in review."""
import json

import pytest
from botocore.exceptions import ClientError

from conftest import BUCKET, ROOT
from platform_publish import push, withdraw
from platform_publish.publish import PushRefused, check_can_set_public_read
from platform_publish.stac import union_bbox
from platform_publish.validate import _same_nodata

EVENT_KEY = "flood-detection/saintes-2026-02/flood-extent.tif"
COLLECTION = "flood-detection/collection.json"


def get(s3, key):
    return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())


def acl_public(s3, key):
    grants = s3.get_object_acl(Bucket=BUCKET, Key=key)["Grants"]
    return any(g["Grantee"].get("URI", "").endswith("AllUsers") and g["Permission"] == "READ" for g in grants)


def do_push(s3, paths, root_url=ROOT):
    return push(*paths, bucket=BUCKET, s3=s3, root_url=root_url, verify=False)


def item_hrefs(s3):
    return [l["href"] for l in get(s3, COLLECTION)["links"] if l["rel"] == "item"]


def test_withdraw_reports_failed_deletes(s3, make_project, monkeypatch):
    do_push(s3, make_project())
    delete = s3.delete_objects

    def refuse_one(**kw):
        kept = [o for o in kw["Delete"]["Objects"] if o["Key"] != EVENT_KEY]
        out = delete(**{**kw, "Delete": {"Objects": kept}})
        out["Errors"] = [{"Key": EVENT_KEY, "Code": "AccessDenied", "Message": "no"}]
        return out

    monkeypatch.setattr(s3, "delete_objects", refuse_one)
    res = withdraw("flood-detection", "saintes-2026-02", bucket=BUCKET, s3=s3)
    assert res.delete_failures == [f"{EVENT_KEY}: AccessDenied no"]
    assert EVENT_KEY not in res.uploaded


def test_withdraw_link_match_is_exact(s3, make_project):
    do_push(s3, make_project())
    col = get(s3, COLLECTION)
    lookalike = f"{ROOT}/elsewhere/flood-detection/saintes-2026-02/saintes-2026-02.json"
    col["links"].append({"rel": "item", "href": lookalike, "bbox": [0, 0, 1, 1],
                         "start_datetime": "2026-03-01T00:00:00Z", "end_datetime": "2026-03-02T00:00:00Z"})
    s3.put_object(Bucket=BUCKET, Key=COLLECTION, Body=json.dumps(col).encode())
    withdraw("flood-detection", "saintes-2026-02", bucket=BUCKET, s3=s3)
    assert item_hrefs(s3) == [lookalike]


def test_repush_under_another_root_url_replaces_the_link(s3, make_project):
    paths = make_project()
    do_push(s3, paths)
    do_push(s3, paths, root_url="http://localhost:8000")
    assert item_hrefs(s3) == ["http://localhost:8000/flood-detection/saintes-2026-02/saintes-2026-02.json"]
    selfs = [l["href"] for l in get(s3, COLLECTION)["links"] if l["rel"] == "self"]
    assert selfs == ["http://localhost:8000/flood-detection/collection.json"]


def test_rerun_restores_public_read_on_skipped_files(s3, make_project):
    paths = make_project()
    do_push(s3, paths)
    s3.put_object_acl(Bucket=BUCKET, Key=EVENT_KEY, ACL="private")
    assert not acl_public(s3, EVENT_KEY)
    res = do_push(s3, paths)
    assert EVENT_KEY in res.skipped
    assert acl_public(s3, EVENT_KEY)


def test_probe_left_behind_is_named(s3, monkeypatch):
    def deny(**kw):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "DeleteObject")

    monkeypatch.setattr(s3, "delete_object", deny)
    with pytest.raises(PushRefused, match="left in the bucket"):
        check_can_set_public_read(s3, BUCKET)


def test_union_bbox_plain_and_across_the_antimeridian():
    assert union_bbox([[0, 0, 10, 5], [5, -5, 20, 1]]) == [0, -5, 20, 5]
    assert union_bbox([[170, 0, -170, 5], [-175, -5, -160, 1]]) == [170, -5, -160, 5]
    assert union_bbox([[170, 0, -170, 5], [-10, 0, 10, 1]]) == [170, 0, 10, 5]
    assert union_bbox([[170, 0, -170, 5], [-180, 0, 180, 1]]) == [-180, 0, 180, 5]


def test_nan_nodata_equals_nan_nodata():
    assert _same_nodata(float("nan"), float("nan"))
    assert not _same_nodata(float("nan"), -9999.0)
    assert _same_nodata(255, 255)
