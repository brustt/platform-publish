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


def layer_key(project_slug: str, event_slug: str, layer_slug: str, ext: str = "tif") -> str:
    return f"{project_slug}/{event_slug}/{layer_slug}.{ext}"


def url(root: str, key: str) -> str:
    return f"{root.rstrip('/')}/{key}"


def collection_root(col: dict, project_slug: str) -> str | None:
    """The root URL a Collection was written with, read back from its own self link."""
    tail = f"/{project_slug}/collection.json"
    for l in col.get("links", []):
        if l["rel"] == "self" and l["href"].endswith(tail):
            return l["href"][:-len(tail)]
    return None


def item_hrefs(col: dict, project_slug: str, item_key: str) -> set[str]:
    """The exact href an Event's item link has in this Collection, whatever root URL it was pushed with."""
    root = collection_root(col, project_slug)
    return {url(root, item_key)} if root is not None else set()


def union_bbox(bboxes: list[list[float]]) -> list[float]:
    """Union of WGS84 boxes; a box with west > east crosses the antimeridian (STAC convention)."""
    south, north = min(b[1] for b in bboxes), max(b[3] for b in bboxes)
    if all(b[0] <= b[2] for b in bboxes):
        return [min(b[0] for b in bboxes), south, max(b[2] for b in bboxes), north]
    if any(b[2] - b[0] >= 360 for b in bboxes):
        return [-180, south, 180, north]
    spans = [(w := b[0] % 360, e if (e := b[2] % 360) >= w else e + 360) for b in bboxes]  # unwrap onto [0, 720)
    west, east = min(w for w, _ in spans), max(e for _, e in spans)
    if east - west >= 360:
        return [-180, south, 180, north]
    wrap = lambda x: (x + 180) % 360 - 180  # noqa: E731
    return [wrap(west), south, wrap(east), north]


def build_item(project: dict, event: dict, layers: list, root: str, updated: str) -> dict:
    """The Event's Item. `layers` are the loaded Layers of the Event, in manifest order."""
    p, e = project["slug"], event["event"]
    k = keys(p, e)
    # the Event's footprint is the union extent of its Layers; with one Layer it is that footprint
    bbox = union_bbox([l.bbox for l in layers])
    footprints = [l.footprint for l in layers]
    if len(layers) == 1:
        geometry = footprints[0]
    elif all(f["type"] == "Polygon" for f in footprints):
        geometry = {"type": "MultiPolygon", "coordinates": [f["coordinates"] for f in footprints]}
    else:
        geometry = _bbox_polygon(bbox)
    assets = {l.slug: l.asset(project, e, root, order) for order, l in enumerate(layers)}
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
        "extent": link_extent([]),
        "brustt:attribution": project["attribution"],
        "links": [
            {"rel": "self", "href": url(root, f"{p}/collection.json"), "type": "application/json"},
            {"rel": "root", "href": url(root, "catalog.json"), "type": "application/json"},
            {"rel": "parent", "href": url(root, "catalog.json"), "type": "application/json"},
        ],
    }


def link_extent(links: list[dict]) -> dict:
    """Collection extent from its item links; the world and an open interval when none remain."""
    items = [l for l in links if l["rel"] == "item"]
    if not items:
        return {"spatial": {"bbox": [[-180, -90, 180, 90]]}, "temporal": {"interval": [[None, None]]}}
    return {
        "spatial": {"bbox": [union_bbox([l["bbox"] for l in items])]},
        "temporal": {"interval": [[min(l["start_datetime"] for l in items),
                                   max(l["end_datetime"] for l in items)]]},
    }


def update_collection(col: dict, project: dict, item: dict, root: str) -> dict:
    """Refresh Project metadata, add the Event link if absent, recompute extents from linked Items."""
    col.update({"title": project["title"], "description": project["description"],
                "license": project["licence"], "brustt:attribution": project["attribution"]})
    if project.get("licence_url"):
        col["brustt:licence_url"] = project["licence_url"]
    href = item["links"][0]["href"]
    p = project["slug"]
    # the same Event pushed under another root URL is replaced, not duplicated
    same = item_hrefs(col, p, keys(p, item["id"])["item"]) | {href}
    links = [l for l in col["links"] if not (l["rel"] == "item" and l["href"] in same)]
    for l in links:  # keep the Collection on the same root as its Items
        if l["rel"] == "self":
            l["href"] = url(root, keys(p, "")["collection"])
        elif l["rel"] in ("root", "parent"):
            l["href"] = url(root, "catalog.json")
    links.append({"rel": "item", "href": href, "type": "application/geo+json",
                  "title": item["properties"]["title"],
                  "bbox": item["bbox"],
                  "start_datetime": item["properties"]["start_datetime"],
                  "end_datetime": item["properties"]["end_datetime"]})
    col["links"] = links
    col["extent"] = link_extent(links)
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
