# platform-publish

Validate and Publish Earth-observation results to the brustt Platform bucket as static STAC.
It validates and uploads; it never converts (COGs are made by your own pipeline).

```
pip install git+https://github.com/brustt/platform-publish@v0.1.0
platform-publish validate publish/project.yaml publish/saintes-2026-02.publish.yaml
platform-publish push publish/project.yaml publish/saintes-2026-02.publish.yaml \
    --bucket <bucket> --endpoint-url <s3 endpoint> [--profile brustt] [--root-url https://data.brustt.xyz] [--dry-run]
```

Credentials come from boto3's default chain (use a named profile); nothing is stored.
`validate` is offline. `push` refuses on any validation error, uploads Layers (`public-read`), then the
Item, then writes the link in `collection.json` (and `/catalog.json` for a new Project) last.
Concurrent pushes are unsupported.

Version 0.1 covers raster Layers (categorical, or continuous with a colour map or an RGB band mapping); vector Layers follow.

`platform-publish withdraw <project> <event> --bucket ...` unlinks an Event from `collection.json`, then deletes its prefix.
See `examples/` for manifests and `src/platform_publish/schema.json` for the schema.

## Tests
`pip install -e '.[test]' && pytest` (moto, no network). If GDAL/PROJ env vars from another install
(e.g. OTB) are set, unset `PROJ_LIB`, `PROJ_DATA` and `GDAL_DATA` first.
