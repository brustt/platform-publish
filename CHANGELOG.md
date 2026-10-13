# Changelog

Contract changes are additive only. Update `docs/publish.md` in the same change as any behaviour change,
and bump its "Applies to" line at release.

## Unreleased
- Vector Layers (`kind: vector`): a GeoParquet (`file`) plus a PMTiles (`tiles`), always both, one Layer in the Item
  (PMTiles as the asset, GeoParquet as `brustt:download`). Internal layer names are inferred from the PMTiles.
- Vector display hints (`style`): `layer`, `fill_color`, `line_color`, `opacity`; nothing data-driven.
- `auxiliary` Layers: licence and attribution required; prefilled for OpenStreetMap `source_url`s (editable).
- `push` checks every `licence_url` is reachable; `validate` stays offline.
- New dependency: `pyarrow`.

## v0.1.0
- `validate`, `push`, `withdraw` commands and library API.
- Raster Layers: categorical (`categories`) and continuous (`colormap`, `rgb`).
- Static STAC generated: root catalog, Project Collection, Event Item.
- Not yet: vector Layers, post-push public-URL check.
