"""Raster Layers in the Publish Contract: imagery Layers, continuous display, compare, licences."""
import json

import pytest
import yaml

from conftest import BUCKET, PROJECT, ROOT, event_doc, write_raster
from platform_publish import push, validate

RGB = {"bands": [1, 2, 3], "ranges": [[-25, 0], [-30, -5], [0, 1]]}


def imagery(slug, **over):
    layer = {"slug": slug, "file": f"{slug}.tif", "role": "imagery", "kind": "raster",
             "title": slug.upper(), "shown": False, "rgb": RGB}
    layer.update(over)
    return {k: v for k, v in layer.items() if v is not None}


@pytest.fixture
def make_event(tmp_path):
    """Write a Project with a categorical result Layer plus the given extra Layers (3-band float COGs).

    Returns (project_yaml, event_yaml).
    """
    def _make(extra=(), event_over=None, project_over=None, result_over=None):
        write_raster(tmp_path / "flood-extent.tif")
        for layer in extra:
            write_raster(tmp_path / layer["file"], count=3, dtype="float32", nodata=-9999.0,
                         overview="AVERAGE", seed=hash(layer["slug"]) % 1000)
        ev = event_doc(**(result_over or {}))
        ev["layers"] += list(extra)
        ev.update(event_over or {})
        (tmp_path / "project.yaml").write_text(yaml.safe_dump({**PROJECT, **(project_over or {})}))
        (tmp_path / "saintes-2026-02.publish.yaml").write_text(yaml.safe_dump(ev))
        return tmp_path / "project.yaml", tmp_path / "saintes-2026-02.publish.yaml"
    return _make


def get(s3, key):
    return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())


ITEM = "flood-detection/saintes-2026-02/saintes-2026-02.json"
PAIR = (imagery("s1-before", acquired="2026-01-12"), imagery("s1-after", acquired="2026-02-17"))


def test_result_with_two_three_band_imagery_layers_validates_and_pushes(s3, make_event):
    paths = make_event(PAIR, event_over={"compare": ["s1-before", "s1-after"]})
    rep = validate(*paths)
    assert rep.ok, rep.errors

    res = push(*paths, bucket=BUCKET, s3=s3, root_url=ROOT)

    assert sorted(k for k in res.uploaded if k.endswith(".tif")) == [
        f"flood-detection/saintes-2026-02/{s}.tif" for s in ("flood-extent", "s1-after", "s1-before")]
    item = get(s3, ITEM)
    assert list(item["assets"]) == ["flood-extent", "s1-before", "s1-after"]  # manifest order
    assert [a["brustt:order"] for a in item["assets"].values()] == [0, 1, 2]
    after = item["assets"]["s1-after"]
    assert after["brustt:role"] == "imagery" and after["brustt:shown"] is False
    assert after["brustt:rgb"] == {"bands": [1, 2, 3], "ranges": [[-25, 0], [-30, -5], [0, 1]]}
    assert after["brustt:acquired"] == "2026-02-17"
    assert item["properties"]["brustt:compare"] == {"before": "s1-before", "after": "s1-after"}


def errs(rep):
    return " | ".join(rep.errors)


@pytest.mark.parametrize("hint", [
    {"bands": [1, 2], "ranges": [[0, 1], [0, 1]]},                       # two bands
    {"bands": [1, 2, 3], "ranges": [[0, 1], [0, 1]]},                    # a range missing
    {"bands": [1, 2, 3], "ranges": [[0, 1], [0, 1], [0, 1]], "colormap": "viridis"},  # extra key
    {"bands": [1, 1, 2], "ranges": [[0, 1], [0, 1], [0, 1]]},            # a band used twice
    {"bands": [1, 2, 3]},                                                # no value ranges
])
def test_rgb_needs_three_distinct_bands_each_with_a_range(make_event, hint):
    rep = validate(*make_event([imagery("s1-after", rgb=hint)]))
    assert not rep.ok


def test_colormap_and_rgb_together_are_refused(make_event):
    rep = validate(*make_event([imagery("s1-after", colormap={"name": "viridis", "range": [0, 1]})]))
    assert not rep.ok


def test_single_band_with_a_named_colormap_is_accepted(make_event):
    layer = imagery("s1-vv", rgb=None, colormap={"name": "viridis", "band": 2, "range": [-25, 0]})
    assert validate(*make_event([layer])).ok


@pytest.mark.parametrize("acquired", ["last spring", "2026-02-30", "17/02/2026", ""])
def test_acquisition_date_must_be_a_date(make_event, acquired):
    assert not validate(*make_event([imagery("s1-after", acquired=acquired)])).ok


def test_acquisition_date_is_optional(make_event):
    assert validate(*make_event([imagery("s1-after")])).ok


def pushed_assets(s3, paths):
    push(*paths, bucket=BUCKET, s3=s3, root_url=ROOT)
    return get(s3, ITEM)["assets"]


def test_result_and_imagery_inherit_the_project_licence_and_attribution(s3, make_event):
    assets = pushed_assets(s3, make_event([imagery("s1-after")]))
    for slug in ("flood-extent", "s1-after"):
        a = assets[slug]
        assert a["brustt:licence"] == "CC-BY-4.0" and a["brustt:attribution"] == "brustt"
        assert a["brustt:licence_url"] == "https://creativecommons.org/licenses/by/4.0/"


def test_imagery_may_declare_its_own_licence_and_attribution(s3, make_event):
    own = imagery("s1-after", attribution="Contains modified Copernicus Sentinel data 2026",
                  licence="custom", licence_url="https://example.test/legal",
                  source_url="https://dataspace.copernicus.eu")
    a = pushed_assets(s3, make_event([own]))["s1-after"]
    assert a["brustt:attribution"] == "Contains modified Copernicus Sentinel data 2026"
    assert (a["brustt:licence"], a["brustt:licence_url"]) == ("custom", "https://example.test/legal")
    assert a["brustt:source_url"] == "https://dataspace.copernicus.eu"


def test_partial_override_keeps_the_rest_of_the_default(s3, make_event):
    a = pushed_assets(s3, make_event([imagery("s1-after", attribution="ESA")]))["s1-after"]
    assert a["brustt:attribution"] == "ESA" and a["brustt:licence"] == "CC-BY-4.0"


@pytest.mark.parametrize("licence", ["CC-BY-4.0", "ODbL-1.0", "CC0-1.0", "Apache-2.0", "GPL-3.0-or-later", "custom"])
def test_licence_may_be_spdx_or_custom(make_event, licence):
    assert validate(*make_event([imagery("s1-after", licence=licence)])).ok


@pytest.mark.parametrize("licence", ["free to use", "Creative Commons", "CC BY 4.0", "Custom"])
def test_licence_that_is_neither_spdx_nor_custom_is_refused(make_event, licence):
    assert "licence" in errs(validate(*make_event([imagery("s1-after", licence=licence)])))


def test_project_default_licence_must_also_be_spdx_or_custom(make_event):
    assert "licence" in errs(validate(*make_event(project_over={"licence": "free to use"})))


SENTINEL_LEGAL = "https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice"


def test_copernicus_source_prefills_attribution_and_licence(s3, make_event):
    a = pushed_assets(s3, make_event([imagery("s1-after", source="copernicus-sentinel",
                                              acquired="2026-02-17")]))["s1-after"]
    assert a["brustt:attribution"] == "Contains modified Copernicus Sentinel data 2026"
    assert (a["brustt:licence"], a["brustt:licence_url"]) == ("custom", SENTINEL_LEGAL)
    assert a["brustt:source_url"] == "https://dataspace.copernicus.eu"


def test_prefilled_year_is_the_acquisition_year_else_the_event_year(s3, make_event):
    paths = make_event([imagery("s1-old", source="copernicus-sentinel", acquired="2025-12-30"),
                        imagery("s1-undated", source="copernicus-sentinel")])
    assets = pushed_assets(s3, paths)
    assert assets["s1-old"]["brustt:attribution"].endswith("data 2025")
    assert assets["s1-undated"]["brustt:attribution"].endswith("data 2026")  # Event starts 2026-02-15


def test_owner_may_edit_the_prefilled_values(s3, make_event):
    own = imagery("s1-after", source="copernicus-sentinel", attribution="Modified Sentinel-1 data, ESA 2026")
    a = pushed_assets(s3, make_event([own]))["s1-after"]
    assert a["brustt:attribution"] == "Modified Sentinel-1 data, ESA 2026"
    assert a["brustt:licence_url"] == SENTINEL_LEGAL  # the rest stays suggested


def test_prefill_is_not_applied_without_a_source(s3, make_event):
    a = pushed_assets(s3, make_event([imagery("s1-after")]))["s1-after"]
    assert a["brustt:attribution"] == "brustt" and "brustt:source_url" not in a


def test_unknown_source_is_refused(make_event):
    assert not validate(*make_event([imagery("s1-after", source="my-drone")])).ok


def test_compare_must_name_two_layers_of_the_event(make_event):
    rep = validate(*make_event(PAIR, event_over={"compare": ["s1-before", "s1-later"]}))
    assert "compare" in errs(rep) and "s1-later" in errs(rep)
