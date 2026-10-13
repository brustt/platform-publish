# Changelog

Contract changes are additive only. Update `docs/publish.md` in the same change as any behaviour change,
and bump its "Applies to" line at release.

## v0.2.0 (2026-10-13)
- Fix: `validate` (and so `push`) crashed with a `NameError` because `licence` and `sources` were not imported.
- Fix: the post-push URL check requested `<layer>.tif` for a vector Layer (404, exit 2); it now checks the
  PMTiles and the GeoParquet.
- `push` checks public URLs after registering (200, 206 on range, CORS); failures reported, exit 2, no rollback.
  `--skip-url-check` opts out.
- Vector Layers (`kind: vector`): a GeoParquet (`file`) plus a PMTiles (`tiles`), always both, one Layer in the Item
  (PMTiles as the asset, GeoParquet as `brustt:download`). Internal layer names are inferred from the PMTiles.
- Vector display hints (`style`): `layer`, `fill_color`, `line_color`, `opacity`; nothing data-driven.
- `auxiliary` Layers: licence and attribution required; prefilled for OpenStreetMap `source_url`s (editable).
- `push` checks every `licence_url` is reachable; `validate` stays offline.
- New dependency: `pyarrow`.
- `imagery` Layers: optional `acquired` date (`YYYY-MM-DD`, must be a real date) and their own attribution
  and licence; imagery inherits the Project defaults like a result.
- `source: copernicus-sentinel` prefills attribution, licence, licence URL and source URL; owner values win.
- `rgb` bands must be three different bands.
- **Stricter than v0.1.0:** `licence` (Project and Layer) must be an SPDX identifier or `custom`, and
  `acquired` must be a date. A v0.1.0 manifest with a free-text licence is now refused.

## v0.1.0
- `validate`, `push`, `withdraw` commands and library API.
- Raster Layers: categorical (`categories`) and continuous (`colormap`, `rgb`).
- Static STAC generated: root catalog, Project Collection, Event Item.
- Not yet: vector Layers.
