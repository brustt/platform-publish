"""Generate the static STAC documents. Owners never write STAC."""
from datetime import datetime, timezone

STAC_VERSION = "1.0.0"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def keys(project_slug: str, event_slug: str) -> dict:
    return {
        "catalog": "catalog.json",
        "collection": f"{project_slug}/collection.json",
        "item": f"{project_slug}/{event_slug}/{event_slug}.json",
    }


def layer_key(project_slug: str, event_slug: str, layer_slug: str) -> str:
    return f"{project_slug}/{event_slug}/{layer_slug}.tif"


def url(root: str, key: str) -> str:
    return f"{root.rstrip('/')}/{key}"


def build_item(project: dict, event: dict, rasters: dict, root: str, updated: str) -> dict:
    p, e = project["slug"], event["event"]
    k = keys(p, e)
    # the Event's footprint is the union extent of its Layers; with one result raster it is that footprint
    first = event["layers"][0]["slug"]
    infos = [rasters[l["slug"]] for l in event["layers"]]
    bbox = [min(i.bbox[0] for i in infos), min(i.bbox[1] for i in infos),
            max(i.bbox[2] for i in infos), max(i.bbox[3] for i in infos)]
    geometry = rasters[first].footprint if len(infos) == 1 else _bbox_polygon(bbox)
    assets = {}
    for order, layer in enumerate(event["layers"]):
        info = rasters[layer["slug"]]
        a = {
            "href": url(root, layer_key(p, e, layer["slug"])),
            "type": info.media_type,
            "title": layer["title"],
            "roles": ["data", layer["role"]],
            "file:checksum": "1220" + info.sha256,
            "file:size": info.size,
            "proj:code": info.crs,
            "file:nodata": info.nodata,
            "brustt:role": layer["role"],
            "brustt:kind": layer["kind"],
            "brustt:order": order,
            "brustt:shown": layer.get("shown", True),
            "brustt:attribution": layer.get("attribution", project["attribution"]),
            "brustt:licence": layer.get("licence", project["licence"]),
        }
        for hint in ("categories", "colormap", "rgb"):
            if hint in layer:
                a[f"brustt:{hint}"] = layer[hint]
        for src, dst in (("licence_url", "brustt:licence_url"), ("source_url", "brustt:source_url"),
                         ("acquired", "brustt:acquired")):
            if layer.get(src):
                a[dst] = layer[src]
        if "licence_url" not in layer and "licence" not in layer and project.get("licence_url"):
            a["brustt:licence_url"] = project["licence_url"]
        assets[layer["slug"]] = a
    props = {
        "title": event["title"],
        "datetime": None,
        "start_datetime": f"{event['start']}T00:00:00Z",
        "end_datetime": f"{event['end']}T23:59:59Z",
        "updated": updated,
    }
    if event.get("description"):
        props["description"] = event["description"]
    if event.get("compare"):
        props["brustt:compare"] = {"before": event["compare"][0], "after": event["compare"][1]}
    return {
        "type": "Feature", "stac_version": STAC_VERSION, "id": e,
        "geometry": geometry, "bbox": bbox, "properties": props, "assets": assets,
        "links": [
            {"rel": "self", "href": url(root, k["item"]), "type": "application/geo+json"},
            {"rel": "collection", "href": url(root, k["collection"]), "type": "application/json"},
            {"rel": "parent", "href": url(root, k["collection"]), "type": "application/json"},
            {"rel": "root", "href": url(root, k["catalog"]), "type": "application/json"},
        ],
        "collection": p,
    }


def _bbox_polygon(b):
    w, s, e, n = b
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def new_collection(project: dict, root: str) -> dict:
    p = project["slug"]
    return {
        "type": "Collection", "stac_version": STAC_VERSION, "id": p,
        "title": project["title"], "description": project["description"],
        "license": project["licence"],
        "extent": {"spatial": {"bbox": [[-180, -90, 180, 90]]}, "temporal": {"interval": [[None, None]]}},
        "brustt:attribution": project["attribution"],
        "links": [
            {"rel": "self", "href": url(root, f"{p}/collection.json"), "type": "application/json"},
            {"rel": "root", "href": url(root, "catalog.json"), "type": "application/json"},
            {"rel": "parent", "href": url(root, "catalog.json"), "type": "application/json"},
        ],
    }


def update_collection(col: dict, project: dict, item: dict, root: str) -> dict:
    """Refresh Project metadata, add the Event link if absent, recompute extents from linked Items."""
    col.update({"title": project["title"], "description": project["description"],
                "license": project["licence"], "brustt:attribution": project["attribution"]})
    if project.get("licence_url"):
        col["brustt:licence_url"] = project["licence_url"]
    href = item["links"][0]["href"]
    links = [l for l in col["links"] if not (l["rel"] == "item" and l["href"] == href)]
    links.append({"rel": "item", "href": href, "type": "application/geo+json",
                  "title": item["properties"]["title"],
                  "bbox": item["bbox"],
                  "start_datetime": item["properties"]["start_datetime"],
                  "end_datetime": item["properties"]["end_datetime"]})
    col["links"] = links
    items = [l for l in links if l["rel"] == "item"]
    col["extent"] = {
        "spatial": {"bbox": [[min(l["bbox"][0] for l in items), min(l["bbox"][1] for l in items),
                              max(l["bbox"][2] for l in items), max(l["bbox"][3] for l in items)]]},
        "temporal": {"interval": [[min(l["start_datetime"] for l in items),
                                   max(l["end_datetime"] for l in items)]]},
    }
    return col


def new_catalog(root: str) -> dict:
    return {"type": "Catalog", "stac_version": STAC_VERSION, "id": "brustt-platform",
            "description": "Published Results from brustt Earth-observation Projects",
            "links": [{"rel": "self", "href": url(root, "catalog.json"), "type": "application/json"},
                      {"rel": "root", "href": url(root, "catalog.json"), "type": "application/json"}]}


def add_child(cat: dict, project: dict, root: str) -> bool:
    href = url(root, f"{project['slug']}/collection.json")
    if any(l["rel"] == "child" and l["href"] == href for l in cat["links"]):
        return False
    cat["links"].append({"rel": "child", "href": href, "type": "application/json", "title": project["title"]})
    return True
