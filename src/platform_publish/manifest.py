"""Load project.yaml and <event>.publish.yaml and check them against the JSON Schema."""
import json
from dataclasses import dataclass
from datetime import date
from importlib import resources
from pathlib import Path
from urllib.parse import urlparse

import yaml
from jsonschema import Draft202012Validator

DEFAULT_ROOT_URL = "https://data.brustt.xyz"


def _schema() -> dict:
    return json.loads(resources.files("platform_publish").joinpath("schema.json").read_text())


def schema_errors(doc, kind: str) -> list[str]:
    """kind is 'project' or 'event'."""
    schema = _schema()
    sub = {"$ref": f"#/$defs/{kind}", "$defs": schema["$defs"]}
    v = Draft202012Validator(sub)
    out = []
    for e in sorted(v.iter_errors(doc), key=lambda e: list(map(str, e.path))):
        loc = "/".join(map(str, e.path)) or "<root>"
        out.append(f"{loc}: {e.message}")
    return out


@dataclass
class Manifests:
    project: dict
    event: dict
    base_dir: Path  # layer `file:` paths are relative to the event manifest


def load_yaml(path: Path):
    with open(path) as f:
        data = yaml.safe_load(f)
    return _stringify_dates(data)


def _stringify_dates(x):
    if isinstance(x, dict):
        return {k: _stringify_dates(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_stringify_dates(v) for v in x]
    if isinstance(x, date):
        return x.isoformat()
    return x


OSM_DEFAULTS = {
    "attribution": "© OpenStreetMap contributors",
    "licence": "ODbL-1.0",
    "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/",
}
_OSM_HOSTS = ("openstreetmap.org", "geofabrik.de")


def is_osm_source(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _OSM_HOSTS)


def prefill_source_defaults(event: dict) -> list[str]:
    """Suggest attribution and licence for OpenStreetMap-sourced Layers (by `source_url`).

    Only fills what the owner left out, so every suggested value stays editable. Returns notes."""
    notes = []
    for layer in event["layers"]:
        if not is_osm_source(layer.get("source_url", "")):
            continue
        filled = [k for k, v in OSM_DEFAULTS.items() if not layer.get(k)]
        for k in filled:
            layer[k] = OSM_DEFAULTS[k]
        if filled:
            notes.append(f"layer '{layer['slug']}': OpenStreetMap source, prefilled {', '.join(filled)} (edit to override)")
    return notes
