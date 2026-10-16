"""Offline validation of a Project and one Event manifest."""
from dataclasses import dataclass, field
from pathlib import Path

from . import licence, sources
from .layer import Layer, load_layer
from .manifest import Manifests, load_yaml, prefill_source_defaults, schema_errors


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # informational, e.g. prefilled values
    manifests: Manifests | None = None
    layers: list[Layer] = field(default_factory=list)  # in manifest order; usable only when `ok`

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(project_yaml: str | Path, event_yaml: str | Path) -> ValidationReport:
    rep = ValidationReport()
    event_yaml = Path(event_yaml)
    try:
        project = load_yaml(Path(project_yaml))
        event = load_yaml(event_yaml)
    except Exception as e:  # unreadable or malformed YAML
        rep.errors.append(f"cannot read manifest: {e}")
        return rep

    rep.errors += [f"project.yaml {m}" for m in schema_errors(project, "project")]
    rep.errors += [f"{event_yaml.name} {m}" for m in schema_errors(event, "event")]
    if rep.errors:
        return rep  # structure must be right before we look at files

    rep.notes += prefill_source_defaults(event)
    event = sources.with_suggestions(event)
    if not licence.is_valid(project["licence"]):
        rep.errors.append(f"project.yaml: {licence.problem(project['licence'])}")
    if event["start"] > event["end"]:
        rep.errors.append("event start is after end")
    slugs = [l["slug"] for l in event["layers"]]
    if len(set(slugs)) != len(slugs):
        rep.errors.append("duplicate Layer slugs")
    if not any(l["role"] == "result" for l in event["layers"]):
        rep.errors.append("at least one Layer with role 'result' is required")
    for c in event.get("compare", []):
        if c not in slugs:
            rep.errors.append(f"compare names unknown Layer '{c}'")

    base = event_yaml.parent
    rep.manifests = Manifests(project, event, base)
    for manifest_layer in event["layers"]:
        layer = load_layer(manifest_layer, base)
        rep.layers.append(layer)
        rep.errors += layer.errors
    return rep

