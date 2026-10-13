# Changelog

Contract changes are additive only. Update `docs/publish.md` in the same change as any behaviour change,
and bump its "Applies to" line at release.

## Unreleased
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
- Not yet: vector Layers, post-push public-URL check.
