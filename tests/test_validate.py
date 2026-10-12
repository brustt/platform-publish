import pytest

from platform_publish import validate


def errs(rep):
    return " | ".join(rep.errors)


def test_valid_project_passes(make_project):
    rep = validate(*make_project())
    assert rep.ok, rep.errors
    info = rep.rasters["flood-extent"]
    assert info.crs == "EPSG:32630" and info.nodata == 255
    assert len(info.sha256) == 64 and info.bbox[0] < info.bbox[2]


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
