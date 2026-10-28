"""Interactive generator for project.yaml and <event>.publish.yaml.

Looks at the files in `outputs/<event>/`, asks only what cannot be inferred, and runs `validate` on the result.
Re-running updates: values already in the manifests are the defaults and layers already listed are kept as they are.
"""
import os
import re
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
import yaml

from . import licence, sources
from .manifest import load_yaml
from .validate import validate

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
EVENT_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*-[0-9]{4}-(0[1-9]|1[0-2])$")
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
PALETTE = ["#000000", "#1f78b4", "#33a02c", "#e31a1c", "#ff7f00", "#6a3d9a", "#b15928", "#a6cee3"]
MAX_CATEGORIES = 20


class ScaffoldError(Exception):
    pass


class Prompter:
    """Asks questions through `ask`; with `yes`, takes every default and fails where there is none."""

    def __init__(self, ask=None, say=print, yes=False):
        self.ask, self.say, self.yes = ask or input, say, yes

    def text(self, question, default=None, check=None, required=True):
        """A free answer. Blank takes the default; a blank optional answer returns None."""
        while True:
            shown = f" [{default}]" if default not in (None, "") else "" if required else " (optional)"
            if self.yes:
                answer = ""
            else:
                answer = self.ask(f"{question}{shown}: ").strip()
            value = answer or (None if default in (None, "") else str(default))
            if value is None:
                if not required:
                    return None
                if self.yes:
                    raise ScaffoldError(f"{question}: no default to take with --yes")
                self.say("  a value is required")
                continue
            problem = check(value) if check else None
            if not problem:
                return value
            if self.yes:
                raise ScaffoldError(f"{question}: {problem}")
            self.say(f"  {problem}")

    def choice(self, question, options, default):
        return self.text(f"{question} ({'/'.join(options)})", default,
                         lambda v: None if v in options else f"choose one of {', '.join(options)}")

    def flag(self, question, default):
        a = self.text(f"{question} (y/n)", "y" if default else "n",
                      lambda v: None if v.lower() in ("y", "n", "yes", "no") else "answer y or n")
        return a.lower().startswith("y")


# --- checks -----------------------------------------------------------------------------------

def _slug(v):
    return None if SLUG.match(v) else "lowercase letters, digits and single dashes (e.g. flood-extent)"


def _event_slug(v):
    return None if EVENT_SLUG.match(v) else "use <place>-<yyyy>-<mm> (e.g. saintes-2026-02)"


def _day(v):
    try:
        date.fromisoformat(v)
    except ValueError:
        return "use a real date as YYYY-MM-DD"


def _licence(v):
    return None if licence.is_valid(v) else licence.problem(v)


def _color(v):
    return None if COLOR.match(v) else "use #rrggbb"


def _number(v):
    try:
        float(v)
    except ValueError:
        return "use a number"


def _unit(v):
    return _number(v) or (None if 0 <= float(v) <= 1 else "use a number between 0 and 1")


def _slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _rel(path: Path, base: Path) -> str:
    """The manifest-relative address of a file."""
    return Path(os.path.relpath(path.resolve(), base.resolve())).as_posix()


def _num(v):
    f = float(v)
    return int(f) if f.is_integer() else f


# --- project.yaml -----------------------------------------------------------------------------

def ask_project(p: Prompter, current: dict, folder_name: str) -> dict:
    slug = p.text("Project slug (public identity, never reused)", current.get("slug") or _slugify(folder_name), _slug)
    out = {
        "slug": slug,
        "title": p.text("Project title", current.get("title") or slug.replace("-", " ").capitalize()),
        "description": p.text("Project description", current.get("description")),
        "licence": p.text("Licence (SPDX identifier, or 'custom')", current.get("licence") or "CC-BY-4.0", _licence),
    }
    url = p.text("Licence URL", current.get("licence_url"), required=False)
    if url:
        out["licence_url"] = url
    out["attribution"] = p.text("Attribution shown on the map", current.get("attribution"))
    return out


# --- layers -----------------------------------------------------------------------------------

def _categories(path: Path, p: Prompter) -> list[dict]:
    with rasterio.open(path) as src:
        values = np.unique(src.read(1))
        nodata = src.nodata
    values = [int(v) for v in values if nodata is None or v != nodata]
    if len(values) > MAX_CATEGORIES:
        raise ScaffoldError(f"{path.name} has more than {MAX_CATEGORIES} distinct values: it is not categorical")
    p.say(f"  values found (no-data left out): {values}")
    cats = []
    for i, v in enumerate(values):
        label = p.text(f"  label for value {v}", f"value {v}")
        color = p.text(f"  colour for value {v}", PALETTE[i % len(PALETTE)], _color)
        cat = {"value": v, "color": color, "label": label}
        if p.flag(f"  value {v} transparent", False):
            cat["transparent"] = True
        cats.append(cat)
    return cats


def _range(p: Prompter, question: str, default=None) -> list:
    def check(v):
        parts = [x.strip() for x in v.split(",")]
        if len(parts) != 2 or any(_number(x) for x in parts):
            return "use two numbers: min,max"
        if float(parts[0]) >= float(parts[1]):
            return "min must be below max"
    answer = p.text(question + " as min,max", default, check)
    return [_num(x.strip()) for x in answer.split(",")]


def _display_hint(path: Path, p: Prompter) -> dict:
    with rasterio.open(path) as src:
        count, integer = src.count, np.issubdtype(np.dtype(src.dtypes[0]), np.integer)
    default = "rgb" if count >= 3 else "categories" if integer else "colormap"
    kind = p.choice("How is it drawn? categories = classes, colormap = one continuous band, rgb = three bands",
                    ["categories", "colormap", "rgb"], default)
    if kind == "categories":
        return {"categories": _categories(path, p)}
    if kind == "colormap":
        hint = {"name": p.text("  colour map name (e.g. viridis)", "viridis")}
        band = p.text("  band", 1, lambda v: None if v.isdigit() and 1 <= int(v) <= count else f"1 to {count}")
        if int(band) != 1:
            hint["band"] = int(band)
        hint["range"] = _range(p, "  value range")
        return {"colormap": hint}

    def bands_ok(v):
        parts = v.split(",")
        if len(parts) != 3 or not all(x.strip().isdigit() for x in parts):
            return "use three band numbers: r,g,b"
        nums = [int(x) for x in parts]
        return None if len(set(nums)) == 3 and 1 <= min(nums) and max(nums) <= count else f"three different bands, 1 to {count}"
    bands = [int(x) for x in p.text("  bands r,g,b", "1,2,3", bands_ok).split(",")]
    ranges = [_range(p, f"  range of band {b}") for b in bands]
    return {"rgb": {"bands": bands, "ranges": ranges}}


def _auxiliary_fields(layer: dict, p: Prompter) -> None:
    layer["licence"] = p.text("  licence (required for auxiliary Layers)", None, _licence)
    layer["attribution"] = p.text("  attribution (required for auxiliary Layers)")
    for key in ("licence_url", "source_url"):
        v = p.text(f"  {key}", None, required=False)
        if v:
            layer[key] = v


def ask_layer(p: Prompter, path: Path, tiles: Path | None, base: Path, taken: set, has_result: bool) -> dict:
    vector = path.suffix == ".parquet"
    p.say(f"\nNew Layer: {path.name}")
    slug = p.text("  slug", _slugify(path.stem),
                  lambda v: _slug(v) or ("already used" if v in taken else None))
    role = p.choice("  role", ["result", "imagery", "auxiliary"],
                    "auxiliary" if vector else "imagery" if has_result else "result")
    layer = {
        "slug": slug,
        "file": _rel(path, base),
        "role": role,
        "kind": "vector" if vector else "raster",
        "title": p.text("  title", path.stem.replace("-", " ").replace("_", " ").capitalize()),
        "shown": p.flag("  shown by default", role == "result" or vector),
    }
    if vector:
        layer["tiles"] = _rel(tiles, base)
    else:
        if role == "imagery":
            acquired = p.text("  acquisition date", None, _day, required=False)
            source = p.text(f"  data source ({', '.join(sources.SOURCES)}; fills attribution and licence)",
                            None, lambda v: None if v in sources.SOURCES else f"one of {', '.join(sources.SOURCES)}",
                            required=False)
            if acquired:
                layer["acquired"] = acquired
            if source:
                layer["source"] = source
            else:
                attribution = p.text("  attribution (blank = the Project's)", None, required=False)
                if attribution:
                    layer["attribution"] = attribution
    if role == "auxiliary":
        _auxiliary_fields(layer, p)
    if vector:
        style = {}
        for key, check in (("layer", None), ("fill_color", _color), ("line_color", _color), ("opacity", _unit)):
            v = p.text(f"  style.{key}", None, check, required=False)
            if v:
                style[key] = float(v) if key == "opacity" else v
        if style:
            layer["style"] = style
    else:
        layer.update(_display_hint(path, p))
    return layer


def _find_files(folder: Path, say) -> list[tuple[Path, Path | None]]:
    found = []
    for f in sorted(folder.iterdir()) if folder.is_dir() else []:
        if f.suffix in (".tif", ".tiff"):
            found.append((f, None))
        elif f.suffix == ".parquet":
            tiles = f.with_suffix(".pmtiles")
            if tiles.is_file():
                found.append((f, tiles))
            else:
                say(f"skipping {f.name}: a vector Layer needs {tiles.name} next to it")
    return found


# --- event ------------------------------------------------------------------------------------

def scaffold(publish_dir: Path, outputs_dir: Path, event: str | None = None, ask=None, say=print, yes=False) -> int:
    """Write or update project.yaml and one <event>.publish.yaml. Returns an exit code."""
    p = Prompter(ask, say, yes)
    publish_dir.mkdir(parents=True, exist_ok=True)
    project_path = publish_dir / "project.yaml"

    say("== project.yaml ==" + (" (updating)" if project_path.exists() else ""))
    project = ask_project(p, load_yaml(project_path) if project_path.exists() else {},
                          publish_dir.resolve().parent.name)

    folders = sorted(d.name for d in outputs_dir.iterdir() if d.is_dir() and EVENT_SLUG.match(d.name)) \
        if outputs_dir.is_dir() else []
    say("\n== event ==" + (f" (outputs: {', '.join(folders)})" if folders else ""))
    event = event or p.text("Event slug (<place>-<yyyy>-<mm>)", folders[-1] if folders else None, _event_slug)
    event_path = publish_dir / f"{event}.publish.yaml"
    current = load_yaml(event_path) if event_path.exists() else {}
    if current:
        say(f"updating {event_path.name}")

    place, year, month = event.rsplit("-", 2)
    default_title = f"{place.replace('-', ' ').title()}, {date(int(year), int(month), 1):%B %Y}"
    doc = {"event": event, "title": p.text("Event title", current.get("title") or default_title)}
    doc["start"] = p.text("Start of the event itself (YYYY-MM-DD)", current.get("start"), _day)
    doc["end"] = p.text("End of the event itself (YYYY-MM-DD)", current.get("end") or doc["start"],
                        lambda v: _day(v) or ("end is before start" if v < doc["start"] else None))
    description = p.text("Event description", current.get("description"), required=False)
    if description:
        doc["description"] = description

    layers = list(current.get("layers", []))
    known = {(publish_dir / l["file"]).resolve() for l in layers}
    taken = {l["slug"] for l in layers}
    for l in layers:
        say(f"kept Layer '{l['slug']}'")
    for path, tiles in _find_files(outputs_dir / event, say):
        if path.resolve() in known:
            continue
        layer = ask_layer(p, path, tiles, publish_dir, taken, any(l["role"] == "result" for l in layers))
        taken.add(layer["slug"])
        layers.append(layer)
    if not layers:
        raise ScaffoldError(f"no Layers: put .tif (or .parquet + .pmtiles) files in {outputs_dir / event}")
    doc["layers"] = layers
    say("\nLayers are drawn in list order, bottom first: reorder them in the file if needed.")

    slugs = [l["slug"] for l in layers]
    if len(slugs) >= 2:
        def pair_ok(v):
            parts = [x.strip() for x in v.split(",")]
            return None if len(parts) == 2 and all(x in slugs for x in parts) else f"two of: {', '.join(slugs)}"
        pair = p.text("Compare pair, before then after (two Layer slugs)", ",".join(current.get("compare", [])),
                      pair_ok, required=False)
        if pair:
            doc["compare"] = [x.strip() for x in pair.split(",")]

    if not p.flag(f"\nWrite {project_path} and {event_path}", True):
        say("nothing written")
        return 1
    project_path.write_text(yaml.safe_dump(project, sort_keys=False, allow_unicode=True))
    event_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    say(f"wrote {project_path}\nwrote {event_path}")

    report = validate(project_path, event_path)
    for m in report.notes:
        say(f"note: {m}")
    for m in report.errors:
        say(f"error: {m}")
    say("valid" if report.ok else f"{len(report.errors)} error(s): fix the files or the data, then run validate")
    return 0 if report.ok else 1
