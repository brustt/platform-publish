"""push: validate, upload Layers, upload the Item, register the link last."""
import json
from dataclasses import dataclass, field

import boto3
import requests
from botocore.exceptions import ClientError

from . import stac
from .manifest import DEFAULT_ROOT_URL
from .validate import validate


class PushRefused(Exception):
    def __init__(self, errors):
        super().__init__("push refused:\n  " + "\n  ".join(errors))
        self.errors = errors


@dataclass
class PushResult:
    uploaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    registered: list[str] = field(default_factory=list)  # catalog files written
    dry_run: bool = False
    url_problems: list[str] = field(default_factory=list)  # failed public-URL checks; nothing is rolled back


def make_client(profile=None, endpoint_url=None):
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return session.client("s3", endpoint_url=endpoint_url)


def _get_json(s3, bucket, key):
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def _put_json(s3, bucket, key, doc, acl="public-read"):
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(doc, indent=2).encode(),
                  ContentType="application/json", ACL=acl,
                  CacheControl="public, max-age=60, must-revalidate")


def _remote_checksum(s3, bucket, key):
    try:
        return s3.head_object(Bucket=bucket, Key=key)["Metadata"].get("sha256")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def check_can_set_public_read(s3, bucket):
    """Early check, before any real write: the credential must be able to set public-read."""
    key = ".platform-publish-probe"
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=b"", ACL="public-read")
        s3.delete_object(Bucket=bucket, Key=key)
    except ClientError as e:
        raise PushRefused([f"credential cannot write public-read objects: {e}"]) from e


ORIGIN = "https://brustt.xyz"


def check_public_urls(urls, ranged, get=None, origin=ORIGIN):
    """Report (never raise) what is wrong with the public URLs: 200 (206 on a range request) and CORS."""
    get = get or (lambda u, h: requests.get(u, headers=h, timeout=30, stream=True))
    problems = []
    for u in urls:
        headers = {"Origin": origin}
        want = 200
        if u in ranged:
            headers["Range"] = "bytes=0-1"
            want = 206
        try:
            r = get(u, headers)
        except Exception as e:
            problems.append(f"{u}: not reachable ({e})")
            continue
        if r.status_code != want:
            problems.append(f"{u}: expected {want}, got {r.status_code}")
        elif r.headers.get("Access-Control-Allow-Origin") not in ("*", origin):
            problems.append(f"{u}: no CORS header for {origin}")
    return problems
def _layer_files(rep, layer, p, e, base):
    """(key, local path, sha256, content type) for each file of a Layer: one for a raster, two for a vector."""
    s = layer["slug"]
    if layer["kind"] == "vector":
        info = rep.vectors[s]
        return [
            (stac.layer_key(p, e, s, "parquet"), (base / layer["file"]).resolve(), info.parquet_sha256, info.parquet_type),
            (stac.layer_key(p, e, s, "pmtiles"), (base / layer["tiles"]).resolve(), info.pmtiles_sha256, info.pmtiles_type),
        ]
    return [(stac.layer_key(p, e, s), (base / layer["file"]).resolve(), rep.rasters[s].sha256, "image/tiff")]


def _licence_urls(project, event) -> list[str]:
    urls = [project.get("licence_url")] + [l.get("licence_url") for l in event["layers"]]
    return list(dict.fromkeys(u for u in urls if u))


def url_reachable(url: str, timeout: float = 10.0) -> str | None:
    """None when the URL answers with a non-error status, else a short reason."""
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout)
        if r.status_code in (403, 405, 501):  # some servers refuse HEAD
            r = requests.get(url, stream=True, timeout=timeout)
            r.close()
        return None if r.status_code < 400 else f"HTTP {r.status_code}"
    except requests.RequestException as e:
        return type(e).__name__


def push(project_yaml, event_yaml, *, bucket, s3=None, profile=None, endpoint_url=None,
         root_url=DEFAULT_ROOT_URL, dry_run=False, now=None, verify=True, http_get=None) -> PushResult:
    rep = validate(project_yaml, event_yaml)
    if not rep.ok:
        raise PushRefused(rep.errors)  # no override

    project, event, base = rep.manifests.project, rep.manifests.event, rep.manifests.base_dir
    p, e = project["slug"], event["event"]
    k = stac.keys(p, e)
    updated = now or stac.now()
    item = stac.build_item(project, event, rep.rasters, root_url, updated, rep.vectors)
    res = PushResult(dry_run=dry_run)

    # online checks belong to push: offline `validate` never touches the network
    unreachable = [f"licence URL not reachable: {u} ({why})" for u in _licence_urls(project, event)
                   if (why := url_reachable(u))]
    if unreachable:
        raise PushRefused(unreachable)

    files = [f for layer in event["layers"] for f in _layer_files(rep, layer, p, e, base)]
    if dry_run:
        res.uploaded += [key for key, *_ in files]
        res.uploaded.append(k["item"])
        res.registered += [k["collection"], k["catalog"]]
        return res

    s3 = s3 or make_client(profile, endpoint_url)
    check_can_set_public_read(s3, bucket)

    for key, path, sha, content_type in files:
        if _remote_checksum(s3, bucket, key) == sha:
            res.skipped.append(key)
            continue
        with open(path, "rb") as f:
            s3.put_object(Bucket=bucket, Key=key, Body=f, ACL="public-read",
                          ContentType=content_type, Metadata={"sha256": sha},
                          CacheControl="public, max-age=3600")
        res.uploaded.append(key)

    _put_json(s3, bucket, k["item"], item)
    res.uploaded.append(k["item"])

    # registration: the link writes come last, so a partial upload is never visible
    col = _get_json(s3, bucket, k["collection"])
    col = stac.update_collection(col or stac.new_collection(project, root_url), project, item, root_url)
    cat = _get_json(s3, bucket, k["catalog"])
    cat_changed = cat is None
    cat = cat or stac.new_catalog(root_url)
    cat_changed = stac.add_child(cat, project, root_url) or cat_changed
    _put_json(s3, bucket, k["collection"], col)
    res.registered.append(k["collection"])
    if cat_changed:
        _put_json(s3, bucket, k["catalog"], cat)
        res.registered.append(k["catalog"])

    if verify:  # after registration: report only, nothing is rolled back
        exts = {"raster": ["tif"], "vector": ["pmtiles", "parquet"]}  # a vector Layer is two files
        layer_urls = [stac.url(root_url, stac.layer_key(p, e, l["slug"], ext))
                      for l in event["layers"] for ext in exts[l["kind"]]]
        res.url_problems = check_public_urls(layer_urls + [stac.url(root_url, k["item"])],
                                             set(layer_urls), http_get)
    return res


def withdraw(project_slug, event_slug, *, bucket, s3=None, profile=None, endpoint_url=None,
             dry_run=False) -> PushResult:
    """Reverse registration: drop the link from collection.json first, then delete the Event's prefix."""
    k = stac.keys(project_slug, event_slug)
    prefix = f"{project_slug}/{event_slug}/"
    s3 = s3 or make_client(profile, endpoint_url)
    col = _get_json(s3, bucket, k["collection"])
    if col is None:
        raise PushRefused([f"no such Project '{project_slug}' in the bucket"])
    item_suffix = "/" + k["item"]
    links = [l for l in col["links"] if not (l["rel"] == "item" and l["href"].endswith(item_suffix))]
    listed = [o["Key"] for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
              for o in page.get("Contents", [])]
    res = PushResult(dry_run=dry_run)
    unlink = len(links) != len(col["links"])
    if not unlink:
        msg = f"Event '{event_slug}' is not published in '{project_slug}'"
        if listed:
            msg += f" ({len(listed)} unlinked objects remain under '{prefix}'; nothing was changed)"
        raise PushRefused([msg])
    if dry_run:
        res.registered += [k["collection"]] if unlink else []
        res.uploaded += listed  # keys that would be deleted
        return res
    if unlink:
        col["links"] = links
        col["extent"] = stac.link_extent(links)
        _put_json(s3, bucket, k["collection"], col)  # link first, so nothing half-deleted is visible
        res.registered.append(k["collection"])
    for i in range(0, len(listed), 1000):
        s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": x} for x in listed[i:i + 1000]]})
    res.uploaded = listed  # reused field: keys deleted
    return res
