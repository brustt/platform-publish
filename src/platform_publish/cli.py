"""Thin CLI over the library: validate, push."""
import argparse
import os
import sys

from .manifest import DEFAULT_ROOT_URL
from .publish import PushRefused, push, withdraw
from .validate import validate


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="platform-publish")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "push"):
        sp = sub.add_parser(name)
        sp.add_argument("project", help="path to project.yaml")
        sp.add_argument("event", help="path to <event>.publish.yaml")
    wp = sub.add_parser("withdraw", help="unpublish an Event: unlink it, then delete its prefix")
    wp.add_argument("project_slug")
    wp.add_argument("event_slug")
    pp = sub.choices["push"]
    pp.add_argument("--bucket", default=os.environ.get("PLATFORM_PUBLISH_BUCKET"))
    pp.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    pp.add_argument("--endpoint-url", default=os.environ.get("PLATFORM_PUBLISH_ENDPOINT_URL"))
    pp.add_argument("--root-url", default=DEFAULT_ROOT_URL)
    pp.add_argument("--dry-run", action="store_true")
    for sp in (wp,):
        sp.add_argument("--bucket", default=os.environ.get("PLATFORM_PUBLISH_BUCKET"))
        sp.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
        sp.add_argument("--endpoint-url", default=os.environ.get("PLATFORM_PUBLISH_ENDPOINT_URL"))
        sp.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "validate":
        rep = validate(a.project, a.event)
        for m in rep.errors:
            print(f"error: {m}", file=sys.stderr)
        print("valid" if rep.ok else f"{len(rep.errors)} error(s)")
        return 0 if rep.ok else 1

    if a.cmd == "withdraw":
        if not a.bucket:
            ap.error("--bucket (or PLATFORM_PUBLISH_BUCKET) is required")
        try:
            res = withdraw(a.project_slug, a.event_slug, bucket=a.bucket, profile=a.profile,
                           endpoint_url=a.endpoint_url, dry_run=a.dry_run)
        except PushRefused as e:
            print(e, file=sys.stderr)
            return 1
        for k in res.registered:
            print(f"{'would unlink' if res.dry_run else 'unlinked'} {k}")
        for k in res.uploaded:
            print(f"{'would delete' if res.dry_run else 'deleted'} {k}")
        return 0

    if not a.bucket and not a.dry_run:
        ap.error("--bucket (or PLATFORM_PUBLISH_BUCKET) is required")
    try:
        res = push(a.project, a.event, bucket=a.bucket, profile=a.profile, endpoint_url=a.endpoint_url,
                   root_url=a.root_url, dry_run=a.dry_run)
    except PushRefused as e:
        print(e, file=sys.stderr)
        return 1
    verb = "would upload" if res.dry_run else "uploaded"
    for k in res.uploaded:
        print(f"{verb} {k}")
    for k in res.skipped:
        print(f"skipped {k} (checksum matches)")
    for k in res.registered:
        print(f"{'would register' if res.dry_run else 'registered'} {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
