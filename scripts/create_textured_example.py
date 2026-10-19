"""Build a texture-first package through the standard Forge3D API; no trusted Python.

Accepts the PNG + panel JSON produced by casual-lowpoly-props/generate_package_atlas.py.
"""
import argparse
import json
from pathlib import Path

from forge3d.client import Client


def atlas_box_scene(asset, layout, name="Textured package"):
    width, height = layout["size"]
    if width < 1 or height < 1:
        raise ValueError("Invalid atlas dimensions")
    sides = ["front", "back", "left", "right", "top", "bottom"]
    if set(layout["faces"]) != set(sides):
        raise ValueError("Atlas must define all six faces")
    coordinates = []
    for side in sides:
        x0, y0, x1, y1 = layout["faces"][side]
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height and x1-x0 > 2 and y1-y0 > 2):
            raise ValueError("Invalid atlas panel rectangle")
        u0, u1 = (x0+1)/width, (x1-1)/width
        vb, vt = 1-(y1-1)/height, 1-(y0+1)/height
        coordinates.append([[u0,vb],[u1,vb],[u1,vt],[u0,vt]])
    return {"name": name, "frame_end": 1, "export_fbx": True,
        "asset_checks": {"target_use": "packaging", "max_tris": 100},
        "materials": [{"id": "package_print", "roughness": 0.85,
            "base_color_texture": {"asset": asset, "uv_map": "UV_Main", "extension": "EXTEND"}}],
        "objects": [{"id": "Package_LP", "type": "mesh", "smooth": False, "material": "package_print",
            "vertices": [[-.3,-.06,0],[.3,-.06,0],[.3,.06,0],[-.3,.06,0],[-.3,-.06,.4],[.3,-.06,.4],[.3,.06,.4],[-.3,.06,.4]],
            "faces": [[0,1,5,4],[2,3,7,6],[3,0,4,7],[1,2,6,5],[4,5,6,7],[3,2,1,0]],
            "uv": {"mode": "explicit", "name": "UV_Main", "coordinates": coordinates}}],
        "camera": {"location": [0.8,-1.25,0.75], "target": [0,0,.2], "lens": 55},
        "lights": [{"id":"key","location":[1,-2,3],"target":[0,0,.2],"energy":100,"size":3}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas", type=Path, required=True)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--name", default="Texture-first / package")
    args = parser.parse_args()
    layout = json.loads(args.layout.read_text(encoding="utf-8"))
    # Validate the layout before making a project.
    atlas_box_scene("placeholder.png", layout)
    client = Client()
    client.ensure()
    project = client.request("/api/projects", {"name": args.name})
    prefix = f"/api/projects/{project['id']}"
    texture = client.request(prefix + "/assets", {"source": str(args.atlas.resolve())})
    scene = atlas_box_scene(texture["asset"], layout, args.name)
    job = client.request(prefix + "/build", {"scene":scene,"render":{"enabled":True,"width":800,"height":640,"samples":16}})
    result = client.wait(job["id"])
    if result["status"] != "succeeded":
        raise RuntimeError(result)
    archive = client.request(prefix + "/archive", {})
    print(json.dumps({"project":project["id"],"job":result,"archive":archive,"viewer":client.url+"/?project="+project["id"]}, indent=2))


if __name__ == "__main__":
    main()
