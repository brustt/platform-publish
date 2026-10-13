# Publishing a result with `platform-publish`

> Applies to **platform-publish v0.1.0**. To read the page for another version, open this file at that git tag
> (GitHub: switch the branch/tag selector). Changes between versions are listed in [`CHANGELOG.md`](../CHANGELOG.md).

`platform-publish` checks your result files and uploads them to the Platform bucket as static STAC.
It **validates and uploads; it never converts.** Your own pipeline must produce the Cloud-Optimized GeoTIFFs.
You never write STAC: the root catalog, your Project's Collection and the Event's Item are generated.

## 1. Install

```bash
pip install git+https://github.com/brustt/platform-publish@v0.1.0
# or, for a non-Python Project:
pipx install git+https://github.com/brustt/platform-publish@v0.1.0
```

## 2. Credentials

Nothing is stored by the tool. It uses boto3's default credential chain; the recommended setup is a named profile
in `~/.aws/credentials` holding the bucket-scoped write key, selected with `--profile` or `AWS_PROFILE`.
The credential must be allowed to write objects with `public-read` (`s3:PutObjectAcl`) and to delete objects
(the early check uploads and removes a probe, and `withdraw` deletes).
Bucket creation and the credential itself: see the object-storage tutorial in the `brustt-platform` repository.

## 3. Recommended layout

```
<project-repo>/publish/project.yaml
<project-repo>/publish/<event>.publish.yaml
<project-repo>/outputs/<event>/<layer>.tif      # final files only, git-ignored
```

`file:` paths in an Event manifest are relative to the manifest. Folder name = Event slug, file name = Layer slug,
so local paths map to bucket paths: `<project>/<event>/<layer>.tif`.

## 4. `project.yaml` (once per Project)

```yaml
slug: flood-detection            # lowercase kebab-case; public identity, never reused
title: Flood detection
description: Flood extent mapped from Sentinel-1.
licence: CC-BY-4.0               # SPDX identifier, or "custom"
licence_url: https://creativecommons.org/licenses/by/4.0/   # optional
attribution: brustt              # exact text shown on the map
```

## 5. `<event>.publish.yaml` (one per Event)

```yaml
event: saintes-2026-02           # <place>-<yyyy-mm>
title: Saintes flood, February 2026
start: 2026-02-15                # the event itself, not the imagery dates
end: 2026-02-19
description: Optional text.
compare: [s1-before, s1-after]   # optional: two Layer slugs (before, after)
layers:                          # draw order = list order
  - slug: flood-extent
    file: ../outputs/saintes-2026-02/flood-extent.tif
    role: result                 # result | imagery | auxiliary
    kind: raster
    title: Flood extent
    shown: true                  # on by default
    categories:                  # categorical raster: also the legend
      - {value: 0, color: "#000000", label: No flood, transparent: true}
      - {value: 1, color: "#1f78b4", label: Flooded}
```

### Display hint: exactly one per Layer

| Hint | Use | Fields |
|---|---|---|
| `categories` | categorical raster | list of `value`, `color` (`#rrggbb`), `label`, optional `transparent` |
| `colormap` | continuous, one band | `name` (colour map name), `range: [min, max]`, optional `band` (default 1) |
| `rgb` | continuous, three bands | `bands: [r, g, b]` (1-based), `ranges: [[min,max], [min,max], [min,max]]` |

Derived bands (e.g. a VV/VH ratio) must be precomputed into the COG; there is no band maths.

### Other Layer fields

| Field | Notes |
|---|---|
| `shown` | default visibility; default `true` |
| `acquired` | optional acquisition date (imagery) |
| `attribution`, `licence`, `licence_url`, `source_url` | `result` Layers inherit the Project defaults; `imagery` only when different; **`auxiliary` Layers must set `licence` and `attribution`** |
| `nodata`, `crs`, `bbox`, `media_type`, `checksum` | optional; inferred from the file. **If you declare one and it disagrees with the file, validation fails.** `bbox` is WGS84 `[west, south, east, north]`; `checksum` is the file's SHA-256 |

## 6. Prepare the files

Each raster must be:
- a valid **Cloud-Optimized GeoTIFF** (tiled, COG layout) with **internal overviews**, in its native CRS;
- carry a **declared no-data** value (required on every raster);
- for **categorical** rasters, built with **nearest or mode** overview resampling.

```bash
gdal_translate in.tif out.tif -of COG -co BLOCKSIZE=256 -co OVERVIEW_RESAMPLING=NEAREST   # categorical
gdal_translate in.tif out.tif -of COG -co OVERVIEW_RESAMPLING=AVERAGE                     # continuous
```

## 7. Validate (offline)

```bash
platform-publish validate publish/project.yaml publish/saintes-2026-02.publish.yaml
```

Checks the JSON Schema, slug formats, at least one `result` Layer, `compare` slugs, auxiliary licence/attribution,
COG validity and overviews, no-data, categorical overview content (and the `rio_overview.resampling` tag when the
file has one), band indexes and ranges, and declared-versus-file values. Prints each problem and exits 1 on any.

## 8. Push

```bash
platform-publish push publish/project.yaml publish/saintes-2026-02.publish.yaml \
    --bucket <bucket> --endpoint-url <s3 endpoint> --profile brustt [--root-url URL] [--dry-run]
```

| Option | Default |
|---|---|
| `--bucket` | `PLATFORM_PUBLISH_BUCKET` |
| `--endpoint-url` | `PLATFORM_PUBLISH_ENDPOINT_URL` |
| `--profile` | `AWS_PROFILE` / default chain |
| `--root-url` | `https://data.brustt.xyz` (prefix of every address written in the Item) |
| `--dry-run` | prints what would upload and register; touches nothing |
| `--skip-url-check` | skip the public-URL check after registering |

Order of operations: validate (**any error refuses the push; there is no override**) → check the credential can
set `public-read` → upload each Layer → upload the Item → write the link in `collection.json` (and `/catalog.json`
for a new Project) **last**. A partial upload is therefore never visible on the site.

After registering, `push` requests the public URL of each Layer (a range request, expecting 206) and of the Item
(expecting 200), and checks the CORS header. Failures are printed as warnings and the command exits 2; **nothing is
rolled back** (the Published Result stays registered; fix the bucket and re-run, or `withdraw`).

**Re-running** is safe: Layers whose SHA-256 already matches are skipped. **Updating** a recomputed Event is the
same command; it overwrites the same keys and bumps the Item's last-updated time. There are no versions.

Local development: `push --root-url http://data.brustt.localhost --profile brustt-local --endpoint-url <local s3>`.

## 9. Withdraw

```bash
platform-publish withdraw flood-detection saintes-2026-02 --bucket <bucket> --profile brustt [--dry-run]
```

Removes the Event's link from `collection.json` first, then deletes everything under `<project>/<event>/`.
Other Events and the Project's entry in `/catalog.json` are untouched. Unknown Project or Event: refused.

## 10. Library use

```python
from platform_publish import validate, push, withdraw
report = validate("publish/project.yaml", "publish/saintes-2026-02.publish.yaml")
assert report.ok, report.errors
push("publish/project.yaml", "publish/saintes-2026-02.publish.yaml", bucket="...", profile="brustt")
```

## Limits in this version

- Raster Layers only; vector Layers (GeoParquet + PMTiles) are not supported yet.
- No locking: **concurrent pushes to the same bucket are unsupported.**
- Contract changes are additive only: a newer release reads everything an older one wrote.
