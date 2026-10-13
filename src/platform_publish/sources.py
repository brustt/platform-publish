"""Suggested attribution and licence for known data sources.

A Layer that names a `source` gets these values for every field the owner left out; anything the owner
writes wins, so the suggestion stays editable.
"""
COPERNICUS = "copernicus-sentinel"

SOURCES = [COPERNICUS]


def suggestions(source: str, year: str) -> dict:
    if source == COPERNICUS:
        return {
            "attribution": f"Contains modified Copernicus Sentinel data {year}",
            "licence": "custom",
            "licence_url": "https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice",
            "source_url": "https://dataspace.copernicus.eu",
        }
    raise ValueError(source)


def with_suggestions(event: dict) -> dict:
    """The Event with every Layer's `source` suggestions filled in; the input is left untouched."""
    layers = []
    for layer in event["layers"]:
        if "source" in layer:
            year = layer.get("acquired", event["start"])[:4]
            layer = {**suggestions(layer["source"], year), **layer}
        layers.append(layer)
    return {**event, "layers": layers}
