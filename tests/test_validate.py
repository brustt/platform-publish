import pytest

from platform_publish import validate


def errs(rep):
    return " | ".join(rep.errors)


def test_valid_project_passes(make_project):
    rep = validate(*make_project())
    assert rep.ok, rep.errors
    layer = rep.layers[0]
    asset = layer.asset({"slug": "flood-detection", "attribution": "a", "licence": "CC-BY-4.0"}, "saintes-2026-02",
                        "https://x.test", 0)
    assert asset["proj:code"] == "EPSG:32630" and asset["file:nodata"] == 255
    assert len(asset["file:checksum"]) == 68 and layer.bbox[0] < layer.bbox[2]


def test_validate_is_offline(make_project, monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    assert validate(*make_project()).ok


@pytest.mark.parametrize("slug", ["Flood_Extent", "flood extent", "-bad", "bad-"])
def test_bad_layer_slug(make_project, slug):
    assert "slug" in errs(validate(*make_project(slug=slug)))


@pytest.mark.parametrize("ev", ["saintes", "saintes-2026-13", "Saintes-2026-02", "saintes-26-02"])
def test_bad_event_slug(make_project, ev):
    assert not validate(*make_project(event_over={"event": ev})).ok


def test_bad_project_slug(make_project):
    assert not validate(*make_project(project_over={"slug": "Flood_Detection"})).ok


def test_not_a_cog(make_project):
    rep = validate(*make_project(raster={"cog": False}))
    assert "Cloud-Optimized" in errs(rep) and "no internal overviews" in errs(rep)


def test_average_overviews_on_categorical_refused(make_project):
    rep = validate(*make_project(raster={"overview": "AVERAGE"}))
    assert "nearest or mode" in errs(rep)


def test_mode_overviews_accepted(make_project):
    assert validate(*make_project(raster={"overview": "MODE"})).ok


def test_missing_nodata(make_project):
    assert "no-data" in errs(validate(*make_project(raster={"nodata": None})))


def test_no_result_layer(make_project):
    assert "result" in errs(validate(*make_project(role="imagery")))


def test_auxiliary_needs_licence_and_attribution(make_project):
    rep = validate(*make_project(role="auxiliary", **{}))
    assert "licence" in errs(rep) and "attribution" in errs(rep)


@pytest.mark.parametrize("over,needle", [
    ({"nodata": 0}, "nodata"),
    ({"crs": "EPSG:4326"}, "crs"),
    ({"bbox": [0, 0, 1, 1]}, "bbox"),
    ({"media_type": "image/png"}, "media_type"),
    ({"checksum": "0" * 64}, "checksum"),
])
def test_declared_value_disagreeing_with_file(make_project, over, needle):
    assert needle in errs(validate(*make_project(**over)))


def test_declared_values_that_agree_are_fine(make_project):
    assert validate(*make_project(nodata=255, crs="EPSG:32630")).ok


def test_missing_file(make_project):
    assert "not found" in errs(validate(*make_project(file="nope.tif")))


CONT = dict(categories=None, nodata=-9999.0)


def cont(raster_over=None, **layer):
    return dict(raster={"count": 3, "dtype": "float32", "nodata": -9999.0, "overview": "AVERAGE",
                        **(raster_over or {})}, **{"categories": None, **layer})


def test_continuous_colormap_single_band(make_project):
    rep = validate(*make_project(**cont(raster_over={"count": 1}, colormap={"name": "viridis", "range": [-25, 0]})))
    assert rep.ok, rep.errors  # average overviews are fine on a continuous raster


def test_continuous_rgb_three_bands(make_project):
    rgb = {"bands": [1, 2, 3], "ranges": [[-25, 0], [-30, -5], [0, 1]]}
    assert validate(*make_project(**cont(rgb=rgb))).ok


def test_rgb_band_beyond_file(make_project):
    rgb = {"bands": [1, 2, 4], "ranges": [[-25, 0], [-30, -5], [0, 1]]}
    assert "band" in errs(validate(*make_project(**cont(rgb=rgb))))


def test_bad_range(make_project):
    assert "min < max" in errs(validate(*make_project(**cont(colormap={"name": "viridis", "range": [5, 5]}))))


def test_exactly_one_display_hint(make_project):
    assert not validate(*make_project(**cont())).ok  # none
    both = {"colormap": {"name": "viridis", "range": [0, 1]}, "categories": [{"value": 0, "color": "#000000", "label": "a"}]}
    assert not validate(*make_project(raster={"dtype": "float32", "nodata": -9999.0}, **both)).ok


def test_continuous_still_needs_nodata(make_project):
    rep = validate(*make_project(**cont(raster_over={"nodata": None}, colormap={"name": "viridis", "range": [-25, 0]})))
    assert "no-data" in errs(rep)


def test_resampling_tag_checked_when_present(make_project, monkeypatch):
    import importlib
    v = importlib.import_module("platform_publish.layer")
    real = v.inspect

    def tagged(tag):
        def f(path, categorical=True):
            info = real(path, categorical)
            info.overview_resampling = tag
            return info
        return f
    paths = make_project()
    monkeypatch.setattr(v, "inspect", tagged("average"))
    assert "average" in errs(validate(*paths))
    monkeypatch.setattr(v, "inspect", tagged("mode"))
    assert validate(*paths).ok


def test_resampling_tag_checked_without_nodata(make_project, monkeypatch):
    import importlib
    v = importlib.import_module("platform_publish.layer")
    real = v.inspect

    def tagged(path, categorical=True):
        info = real(path, categorical)
        info.overview_resampling = "average"
        return info
    monkeypatch.setattr(v, "inspect", tagged)
    e = errs(validate(*make_project(raster={"nodata": None})))
    assert "no-data" in e and "average" in e
