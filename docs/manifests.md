# What the manifests must contain

> Applies to **platform-publish v0.2.0**. The source of truth is `src/platform_publish/schema.json` and `validate.py`;
> this page is the same rules in one place. For the whole publishing flow see [publish.md](publish.md).

A Project repo holds two kinds of manifest, next to each other:

```
<project-repo>/publish/project.yaml                 # once per Project
<project-repo>/publish/<event>.publish.yaml         # one per Event
<project-repo>/outputs/<event>/<layer>.tif|.parquet|.pmtiles
```

**Generate them** instead of typing them: `platform-publish scaffold publish/` asks only what cannot be read from the
files, runs `validate` at the end, and on a re-run keeps what is already there (see [the end of this page](#generate-or-update-with-scaffold)).

Unknown keys are refused: both manifests are checked with `additionalProperties: false`, so a typo or a field from a
newer version fails `validate` instead of being ignored.

## `project.yaml`

| Key | | Rule |
|---|---|---|
| `slug` | **required** | Lowercase kebab-case (`flood-monitoring`). The public address of the Project; never reused. |
| `title` | **required** | Non-empty text. |
| `description` | **required** | Non-empty text. |
| `licence` | **required** | An SPDX identifier (`CC-BY-4.0`) or the word `custom`. Checked offline against a bundled list. |
| `attribution` | **required** | The exact text shown on the map. |
| `licence_url` | optional | Checked reachable by `push` (not by `validate`). |

`result` and `imagery` Layers inherit `licence`, `licence_url` and `attribution` from here.

## `<event>.publish.yaml`

### Event level

| Key | | Rule |
|---|---|---|
| `event` | **required** | `<place>-<yyyy>-<mm>` (`saintes-2026-02`), month `01` to `12`. Must be the folder name under `outputs/`. |
| `title` | **required** | Non-empty text. |
| `start`, `end` | **required** | `YYYY-MM-DD`, the dates of the event itself, not of the imagery. `start` must not be after `end`. |
| `layers` | **required** | At least one Layer, listed bottom first (draw order). Slugs unique. **At least one must have `role: result`.** |
| `description` | optional | Non-empty text. |
| `compare` | optional | Exactly two Layer slugs, before then after. Both must exist in `layers`. |

### Layer level

Required on every Layer:

| Key | Rule |
|---|---|
| `slug` | Lowercase kebab-case, unique in the Event. Becomes the file name in the bucket. |
| `file` | Path relative to the manifest. The GeoTIFF (raster) or the GeoParquet (vector). |
| `role` | `result` (what the Event is about), `imagery` (supporting imagery), or `auxiliary` (context data such as buildings). |
| `kind` | `raster` or `vector`. |
| `title` | Non-empty text. |

Exactly one of these depends on the kind:

| `kind` | Required | Forbidden |
|---|---|---|
| `raster` | exactly one display hint: `categories`, `colormap` or `rgb` | `tiles`, `style` |
| `vector` | `tiles` (the PMTiles, path relative to the manifest) | `categories`, `colormap`, `rgb`, `nodata` |

Optional on any Layer:

| Key | Rule |
|---|---|
| `shown` | Visible by default. Defaults to `true`. |
| `attribution`, `licence`, `licence_url`, `source_url` | Override the Project's. **An `auxiliary` Layer must set `licence` and `attribution`.** |
| `source` | `copernicus-sentinel`: fills `attribution`, `licence`, `licence_url`, `source_url` for you. Anything you write wins. |
| `acquired` | `YYYY-MM-DD`, a real date. Meant for imagery. |
| `nodata`, `crs`, `bbox`, `media_type`, `checksum` | Normally leave out: they are read from the file. **If you write one and it disagrees with the file, validation fails.** `bbox` is WGS84 `[west, south, east, north]`; `checksum` is the SHA-256. |

An `auxiliary` Layer whose `source_url` is on `openstreetmap.org` or `geofabrik.de` gets the OpenStreetMap
attribution and ODbL licence filled in (and a note from `validate`); anything you write wins.

### Display hints

A raster has exactly one.

| Hint | For | Fields |
|---|---|---|
| `categories` | classes (integers) | list of `{value: int, color: "#rrggbb", label: text, transparent: bool (optional)}`. Values unique. |
| `colormap` | one continuous band | `name` (colour map name), `range: [min, max]` (min below max), `band` (optional, default 1, must exist in the file). |
| `rgb` | three bands | `bands: [r, g, b]` (three different, 1-based, all in the file), `ranges: [[min,max], [min,max], [min,max]]` (min below max). |

There is no band maths: precompute derived bands into the file.

A vector Layer may carry a `style` (all keys optional, nothing data-driven):

| Key | Rule |
|---|---|
| `layer` | Name of the layer inside the PMTiles. **Required when the PMTiles holds more than one**; must exist. |
| `fill_color`, `line_color` | `#rrggbb`. |
| `opacity` | Number from 0 to 1. |

## What the files must be

`platform-publish` validates and uploads; it never converts. Your pipeline must produce:

| Layer | Requirement |
|---|---|
| Raster | A valid **Cloud-Optimized GeoTIFF** (GTiff driver, COG layout) with a CRS and **internal** overviews (no `.ovr`). |
| Raster | A **declared no-data** value in the file. |
| Categorical raster | Overviews built with **nearest or mode** resampling, so they contain only the declared `categories` values (plus no-data). |
| Vector | **Both** files: a GeoParquet (`file`) **and** a PMTiles (`tiles`). |

Conversion recipes are in [publish.md](publish.md) section 6.

## Minimal and complete examples

Minimal: the least that validates (one categorical result).

```yaml
# project.yaml
slug: flood-monitoring
title: Flood monitoring
description: Flood extent mapped from a Sentinel-1 radar time series.
licence: CC-BY-4.0
attribution: brustt
```

```yaml
# saintes-2026-02.publish.yaml
event: saintes-2026-02
title: Saintes, February 2026
start: 2026-02-01
end: 2026-03-01
layers:
  - slug: flood-extent
    file: ../outputs/saintes-2026-02/flood-extent.tif
    role: result
    kind: raster
    title: Flood extent
    categories:
      - {value: 0, color: "#000000", label: No flood, transparent: true}
      - {value: 1, color: "#1f78b4", label: Flooded}
```

Complete: every optional piece, in one Event.

```yaml
event: saintes-2026-02
title: Saintes, February 2026
start: 2026-02-01
end: 2026-03-01
description: Flood of the Charente around Saintes.
compare: [s1-before, s1-after]
layers:
  - slug: s1-before                    # imagery with a data source: attribution and licence prefilled
    file: ../outputs/saintes-2026-02/s1-before.tif
    role: imagery
    kind: raster
    title: Sentinel-1 before the flood
    shown: false
    acquired: 2026-01-30
    source: copernicus-sentinel
    rgb: {bands: [1, 2, 3], ranges: [[-20, -3], [-26, -9], [2, 12]]}
  - slug: soil-moisture                # continuous, one band
    file: ../outputs/saintes-2026-02/soil-moisture.tif
    role: imagery
    kind: raster
    title: Soil moisture
    colormap: {name: viridis, range: [0, 1]}
  - slug: flood-extent
    file: ../outputs/saintes-2026-02/flood-extent.tif
    role: result
    kind: raster
    title: Flood extent
    categories:
      - {value: 0, color: "#000000", label: No flood, transparent: true}
      - {value: 1, color: "#1f78b4", label: Flooded}
  - slug: buildings                    # vector: needs file + tiles; auxiliary needs licence + attribution
    file: ../outputs/saintes-2026-02/buildings.parquet
    tiles: ../outputs/saintes-2026-02/buildings.pmtiles
    role: auxiliary
    kind: vector
    title: Building footprints
    source_url: https://www.openstreetmap.org/copyright   # prefills attribution and ODbL licence
    style: {layer: buildings, fill_color: "#ff8800", line_color: "#333333", opacity: 0.4}
```

## What the tool does with them

- It reads footprint, bounding box, CRS, no-data, media type, checksums and vector layer names from the files.
- It generates the STAC Item, Collection and catalog entry. You never write STAC.
- `validate` is offline and exits 1 on any error. `push` runs the same checks and refuses on any error, with no override.
- A field not listed on this page is refused as an unknown key, including fields planned for later versions.

## Generate or update with `scaffold`

```bash
platform-publish scaffold publish/                        # asks for the Event slug
platform-publish scaffold publish/ --event saintes-2026-02
platform-publish scaffold publish/ --outputs path/to/outputs   # default: <publish>/../outputs
platform-publish scaffold publish/ --event saintes-2026-02 --yes   # take every default, ask nothing
```

What it does:

1. **`project.yaml`**: asks slug, title, description, licence (default `CC-BY-4.0`), optional licence URL and attribution.
   If the file exists, its values are the defaults.
2. **Event**: asks title (default from the slug), `start`, `end`, optional description.
3. **Layers**: scans `outputs/<event>/` for `.tif`/`.tiff` and for `.parquet` files that have a `.pmtiles` beside them.
   - A file already in the manifest is **kept untouched**, so your edits survive a re-run.
   - A new file is asked about: slug, role, title, `shown`, and by role the acquisition date and data source (imagery), or
     licence, attribution and source URL (auxiliary).
   - For a raster it reads the file to suggest the display hint: the distinct values for `categories` (no-data left out;
     refuses more than 20), or the band count for `rgb`/`colormap`; you give labels, colours and ranges.
   - For a vector it asks the optional `style`.
4. **`compare`**: asks for two Layer slugs, optional.
5. Asks to confirm, writes both files, then runs `validate` and prints any error. Exit code 1 on an error or if you decline.

What it does not do: convert files, reorder Layers (edit the list: it is the draw order), or remove a Layer whose file
is gone (`validate` reports it).
