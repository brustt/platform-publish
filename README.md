# platform-publish

Validate and Publish Earth-observation results to the brustt Platform bucket as static STAC.
It validates and uploads; it never converts (COGs are made by your own pipeline).

```
pip install git+https://github.com/brustt/platform-publish@v0.2.0
platform-publish validate publish/project.yaml publish/saintes-2026-02.publish.yaml
platform-publish push publish/project.yaml publish/saintes-2026-02.publish.yaml \
    --bucket <bucket> --endpoint-url <s3 endpoint> [--profile brustt] [--root-url https://data.brustt.xyz] [--dry-run]
```

Credentials come from boto3's default chain (use a named profile); nothing is stored.
`validate` is offline. `push` refuses on any validation error, uploads Layers (`public-read`), then the
Item, then writes the link in `collection.json` (and `/catalog.json` for a new Project) last.
Concurrent pushes are unsupported.

Version 0.2 covers raster Layers (categorical, or continuous with a colour map or an RGB band mapping), plus vector Layers (a GeoParquet and PMTiles pair) and Auxiliary Layers.

`platform-publish withdraw <project> <event> --bucket ...` unlinks an Event from `collection.json`, then deletes its prefix.
`platform-publish scaffold publish/` writes or updates both manifests by asking only what the files cannot tell it, then validates.
Full guide: [docs/publish.md](docs/publish.md); what each manifest must contain: [docs/manifests.md](docs/manifests.md). Examples in `examples/`; schema in `src/platform_publish/schema.json`.

## Tests
`pip install -e '.[test]' && pytest` (moto, no network). If GDAL/PROJ env vars from another install
(e.g. OTB) are set, unset `PROJ_LIB`, `PROJ_DATA` and `GDAL_DATA` first.
