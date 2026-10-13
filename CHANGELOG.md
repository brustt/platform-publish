# Changelog

Contract changes are additive only. Update `docs/publish.md` in the same change as any behaviour change,
and bump its "Applies to" line at release.

## v0.1.1 (unreleased)
- `withdraw <project> --project`: remove a whole Project from `/catalog.json`, then delete its prefix (brustt/brustt-platform#44).
- `list [project [event]]`: walk the public catalog over HTTP and show Projects, Events and Layers; reports broken links (brustt/brustt-platform#45).
- Neither is implemented yet; this entry is the plan. Move it under the release date when tagged, and bump the "Applies to" line in `docs/publish.md`.

## v0.1.0
- `validate`, `push`, `withdraw` commands and library API.
- Raster Layers: categorical (`categories`) and continuous (`colormap`, `rgb`).
- Static STAC generated: root catalog, Project Collection, Event Item.
- Not yet: vector Layers, post-push public-URL check.
