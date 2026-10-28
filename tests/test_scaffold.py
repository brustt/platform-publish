import pytest
import yaml

from platform_publish import validate
from platform_publish.cli import main
from platform_publish.scaffold import ScaffoldError, scaffold

from conftest import write_raster


def says(**replies):
    """An `ask` that answers the first prompt containing a key, and takes the default for any other."""
    table = {k.replace("_", " "): v for k, v in replies.items()}
    return lambda prompt: next((v for k, v in table.items() if k in prompt), "")


PROJECT = dict(Project_description="Floods from SAR", Attribution_shown="brustt")
EVENT = {"Start_of_the_event": "2026-02-15", "End_of_the_event": "2026-02-19"}


@pytest.fixture
def repo(tmp_path):
    """A Project repo with one Event's final files in outputs/."""
    out = tmp_path / "outputs" / "saintes-2026-02"
    out.mkdir(parents=True)
    write_raster(out / "flood-extent.tif")  # categorical, values 0 and 10, no-data 255
    (out / "flood-extent.src.tif").unlink()  # the helper's scratch copy
    return tmp_path


def run(repo, **replies):
    return scaffold(repo / "publish", repo / "outputs", ask=says(**replies), say=lambda *_: None)


def event_doc(repo):
    return yaml.safe_load((repo / "publish" / "saintes-2026-02.publish.yaml").read_text())


def test_first_run_writes_valid_manifests(repo):
    assert run(repo, **PROJECT, **EVENT) == 0
    project = yaml.safe_load((repo / "publish" / "project.yaml").read_text())
    layer = event_doc(repo)["layers"][0]
    assert project["licence"] == "CC-BY-4.0" and "licence_url" not in project
    assert layer["file"] == "../outputs/saintes-2026-02/flood-extent.tif"
    assert layer["role"] == "result" and layer["shown"] is True
    assert [c["value"] for c in layer["categories"]] == [0, 10]
    assert validate(repo / "publish" / "project.yaml", repo / "publish" / "saintes-2026-02.publish.yaml").ok


def test_rerun_keeps_layers_and_adds_new_files(repo):
    run(repo, **PROJECT, **EVENT)
    before = event_doc(repo)["layers"][0]
    write_raster(repo / "outputs" / "saintes-2026-02" / "s1-after.tif", count=3, dtype="float32", nodata=-9999)
    (repo / "outputs" / "saintes-2026-02" / "s1-after.src.tif").unlink()

    assert run(repo, acquisition_date="2026-02-17", data_source="copernicus-sentinel", How_is_it_drawn="rgb",
               range_of_band_1="-20,-3", range_of_band_2="-26,-9", range_of_band_3="2,12",
               Compare_pair="flood-extent,s1-after") == 0
    doc = event_doc(repo)
    assert doc["layers"][0] == before
    new = doc["layers"][1]
    assert new["slug"] == "s1-after" and new["role"] == "imagery" and new["source"] == "copernicus-sentinel"
    assert new["rgb"]["ranges"] == [[-20, -3], [-26, -9], [2, 12]]
    assert doc["compare"] == ["flood-extent", "s1-after"]


def test_invalid_answer_is_asked_again(repo):
    answered = iter(["Not a slug", "flood-detection"])
    base = says(**PROJECT, **EVENT)
    ask = lambda prompt: next(answered) if "Project slug" in prompt else base(prompt)  # noqa: E731
    assert scaffold(repo / "publish", repo / "outputs", ask=ask, say=lambda *_: None) == 0
    assert yaml.safe_load((repo / "publish" / "project.yaml").read_text())["slug"] == "flood-detection"


def test_yes_without_a_default_fails(repo):
    with pytest.raises(ScaffoldError, match="no default"):
        scaffold(repo / "publish", repo / "outputs", yes=True, say=lambda *_: None)


def test_no_layers_fails(tmp_path):
    (tmp_path / "outputs" / "saintes-2026-02").mkdir(parents=True)
    with pytest.raises(ScaffoldError, match="no Layers"):
        scaffold(tmp_path / "publish", tmp_path / "outputs", ask=says(**PROJECT, **EVENT), say=lambda *_: None)


def test_cli_wires_scaffold(repo, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", says(**PROJECT, **EVENT))
    assert main(["scaffold", str(repo / "publish")]) == 0
    assert "valid" in capsys.readouterr().out
