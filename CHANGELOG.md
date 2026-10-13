# Changelog

Contract changes are additive only. Update `docs/publish.md` in the same change as any behaviour change,
and bump its "Applies to" line at release.

## Unreleased
- `push` checks public URLs after registering (200, 206 on range, CORS); failures reported, exit 2, no rollback.
  `--skip-url-check` opts out.

## v0.1.0
- `validate`, `push`, `withdraw` commands and library API.
- Raster Layers: categorical (`categories`) and continuous (`colormap`, `rgb`).
- Static STAC generated: root catalog, Project Collection, Event Item.
- Not yet: vector Layers.
