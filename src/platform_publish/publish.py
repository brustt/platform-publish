"""push: validate, upload Layers, upload the Item, register the link last."""
import json
from dataclasses import dataclass, field

import boto3
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


def push(project_yaml, event_yaml, *, bucket, s3=None, profile=None, endpoint_url=None,
         root_url=DEFAULT_ROOT_URL, dry_run=False, now=None) -> PushResult:
    rep = validate(project_yaml, event_yaml)
    if not rep.ok:
        raise PushRefused(rep.errors)  # no override

    project, event, base = rep.manifests.project, rep.manifests.event, rep.manifests.base_dir
    p, e = project["slug"], event["event"]
    k = stac.keys(p, e)
    updated = now or stac.now()
    item = stac.build_item(project, event, rep.rasters, root_url, updated)
    res = PushResult(dry_run=dry_run)

    if dry_run:
        for layer in event["layers"]:
            res.uploaded.append(stac.layer_key(p, e, layer["slug"]))
        res.uploaded.append(k["item"])
        res.registered += [k["collection"], k["catalog"]]
        return res

    s3 = s3 or make_client(profile, endpoint_url)
    check_can_set_public_read(s3, bucket)

    for layer in event["layers"]:
        key = stac.layer_key(p, e, layer["slug"])
        info = rep.rasters[layer["slug"]]
        if _remote_checksum(s3, bucket, key) == info.sha256:
            res.skipped.append(key)
            continue
        with open((base / layer["file"]).resolve(), "rb") as f:
            s3.put_object(Bucket=bucket, Key=key, Body=f, ACL="public-read",
                          ContentType="image/tiff", Metadata={"sha256": info.sha256},
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
    return res
