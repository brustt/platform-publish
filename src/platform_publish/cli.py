"""Thin CLI over the library: validate, push, withdraw, scaffold."""
import argparse
import os
import sys
from pathlib import Path

from .manifest import DEFAULT_ROOT_URL
from .publish import PushRefused, push, withdraw
from .scaffold import ScaffoldError, scaffold
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
    sc = sub.add_parser("scaffold", help="write or update project.yaml and <event>.publish.yaml by answering questions")
    sc.add_argument("publish_dir", nargs="?", default="publish", help="folder of the manifests (default: publish)")
    sc.add_argument("--outputs", help="folder holding <event>/ with the final files (default: <publish_dir>/../outputs)")
    sc.add_argument("--event", help="Event slug (default: asked)")
    sc.add_argument("--yes", action="store_true", help="take every default, ask nothing")
    pp = sub.choices["push"]
    pp.add_argument("--bucket", default=os.environ.get("PLATFORM_PUBLISH_BUCKET"))
    pp.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    pp.add_argument("--endpoint-url", default=os.environ.get("PLATFORM_PUBLISH_ENDPOINT_URL"))
    pp.add_argument("--root-url", default=DEFAULT_ROOT_URL)
    pp.add_argument("--dry-run", action="store_true")
    pp.add_argument("--skip-url-check", action="store_true", help="do not check the public URLs after registering")
    for sp in (wp,):
        sp.add_argument("--bucket", default=os.environ.get("PLATFORM_PUBLISH_BUCKET"))
        sp.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
        sp.add_argument("--endpoint-url", default=os.environ.get("PLATFORM_PUBLISH_ENDPOINT_URL"))
        sp.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "validate":
        rep = validate(a.project, a.event)
        for m in rep.notes:
            print(f"note: {m}", file=sys.stderr)
        for m in rep.errors:
            print(f"error: {m}", file=sys.stderr)
        print("valid" if rep.ok else f"{len(rep.errors)} error(s)")
        return 0 if rep.ok else 1

    if a.cmd == "scaffold":
        publish_dir = Path(a.publish_dir)
        try:
            return scaffold(publish_dir, Path(a.outputs) if a.outputs else publish_dir.resolve().parent / "outputs",
                            event=a.event, yes=a.yes)
        except ScaffoldError as e:
            print(e, file=sys.stderr)
            return 1
        except (EOFError, KeyboardInterrupt):
            print("\nnothing written", file=sys.stderr)
            return 1

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
                   root_url=a.root_url, dry_run=a.dry_run, verify=not a.skip_url_check)
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
    for m in res.url_problems:
        print(f"warning: {m}", file=sys.stderr)
    if res.url_problems:
        print("registered, but the Published Result is not fully reachable; nothing was rolled back", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
