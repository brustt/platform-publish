"""Load project.yaml and <event>.publish.yaml and check them against the JSON Schema."""
import json
from dataclasses import dataclass
from datetime import date
from importlib import resources
from pathlib import Path

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
