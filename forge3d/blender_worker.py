"""Executed ONLY by Blender's Python, no third-party Python dependencies required."""
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback

import bpy
from mathutils import Vector

request = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
output = Path(request["output"])

def write_json(name, value):
    temporary = output / (name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    # Windows denies replace while a polling reader briefly holds the destination.
    for attempt in range(50):
        try:
            os.replace(temporary, output / name)
            break
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(0.02)

def progress(stage, fraction, **kwargs):
    write_json("progress.json", {"stage": stage, "fraction": fraction, "time": time.time(), **kwargs})
    print(f"FORGE3D {stage} {fraction:.0%}", flush=True)

def aim(obj, target):
    direction = Vector(target) - obj.location
    if direction.length > 0:
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

def import_model(asset):
    file = (Path(request["assets"]) / asset).resolve()
    if not file.is_relative_to(Path(request["assets"]).resolve()):
        raise ValueError("Asset path escapes project")
    before = set(bpy.data.objects)
    ext = file.suffix.lower()
    if ext in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(file))
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=str(file))
    elif ext == ".stl":
        bpy.ops.wm.stl_import(filepath=str(file))
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(file))
    else:
        raise ValueError(f"Unsupported import: {ext}")
    imported = set(bpy.data.objects) - before
    root = bpy.data.objects.new("Imported model", None)
    bpy.context.collection.objects.link(root)
    for obj in imported:
        if obj.parent not in imported:
            obj.parent = root
    return root, imported

def build_scene(spec):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.fps = spec["fps"]
    scene.frame_start = 1
    scene.frame_end = spec["frame_end"]
    scene.unit_settings.system = "METRIC"
    scene.world = bpy.data.worlds.new("Forge World")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (*spec["world_color"], 1)
    background.inputs["Strength"].default_value = 0.4
    materials = {}
    for item in spec["materials"]:
        mat = bpy.data.materials.new(item["id"])
        mat.diffuse_color = item["color"]
        mat.use_nodes = True
        shader = mat.node_tree.nodes.get("Principled BSDF")
        for key, value in {"Base Color": item["color"], "Metallic": item["metallic"], "Roughness": item["roughness"], "Emission Color": item["color"], "Emission Strength": item["emission"]}.items():
            shader.inputs[key].default_value = value
        materials[item["id"]] = mat
    objects = {}
    primitive = {"cube": bpy.ops.mesh.primitive_cube_add, "sphere": bpy.ops.mesh.primitive_uv_sphere_add, "cylinder": bpy.ops.mesh.primitive_cylinder_add, "cone": bpy.ops.mesh.primitive_cone_add, "torus": bpy.ops.mesh.primitive_torus_add, "plane": bpy.ops.mesh.primitive_plane_add}
    for index, item in enumerate(spec["objects"]):
        kind = item["type"]
        imported = []
        if kind in primitive:
            if kind == "torus":
                primitive[kind](major_radius=1, minor_radius=0.08)
            else:
                primitive[kind]()
            obj = bpy.context.object
        elif kind == "mesh":
            mesh = bpy.data.meshes.new(item["id"])
            mesh.from_pydata(item["vertices"], [], item["faces"])
            mesh.update()
            obj = bpy.data.objects.new(item["id"], mesh)
            scene.collection.objects.link(obj)
        elif kind == "import":
            obj, imported = import_model(item["asset"])
        else:
            obj = bpy.data.objects.new(item["id"], None)
            scene.collection.objects.link(obj)
        obj.name = item["id"]
        obj["forge_id"] = item["id"]
        obj["forge_preview_hidden"] = item.get("preview_hidden", False)
        obj.location = item["location"]
        obj.rotation_euler = [math.radians(v) for v in item["rotation"]]
        obj.scale = item["scale"]
        objects[item["id"]] = obj
        for target in [obj, *imported]:
            if target.type != "MESH":
                continue
            if item["material"]:
                target.data.materials.clear()
                target.data.materials.append(materials[item["material"]])
            if item["smooth"]:
                for polygon in target.data.polygons:
                    polygon.use_smooth = True
            for mod in item["modifiers"]:
                mapping = {"bevel": "BEVEL", "subdivision": "SUBSURF", "solidify": "SOLIDIFY", "mirror": "MIRROR", "decimate": "DECIMATE"}
                modifier = target.modifiers.new(mod["type"], mapping[mod["type"]])
                if mod["type"] == "bevel":
                    modifier.width, modifier.segments = mod["amount"], 3
                elif mod["type"] == "subdivision":
                    modifier.levels = modifier.render_levels = mod["levels"]
                elif mod["type"] == "solidify":
                    modifier.thickness = mod["amount"]
                elif mod["type"] == "decimate":
                    modifier.ratio = mod["ratio"]
        for key in item["keyframes"]:
            for field, data_path in [("location", "location"), ("rotation", "rotation_euler"), ("scale", "scale")]:
                if key[field] is not None:
                    values = [math.radians(v) for v in key[field]] if field == "rotation" else key[field]
                    setattr(obj, data_path, values)
                    obj.keyframe_insert(data_path=data_path, frame=key["frame"])
        # glTF export samples Blender actions. Linear interpolation is predictable for AI.
        if obj.animation_data and obj.animation_data.action:
            action = obj.animation_data.action
            if hasattr(action, "layers"):
                for layer in action.layers:
                    for strip in layer.strips:
                        for bag in strip.channelbags:
                            for curve in bag.fcurves:
                                for point in curve.keyframe_points:
                                    point.interpolation = "LINEAR"
            elif hasattr(action, "fcurves"):
                for curve in action.fcurves:
                    for point in curve.keyframe_points:
                        point.interpolation = "LINEAR"
        progress("modeling", 0.1 + 0.3 * (index + 1) / max(1, len(spec["objects"])), object=item["id"])
    for item in spec["objects"]:
        if item["parent"]:
            objects[item["id"]].parent = objects[item["parent"]]
    camera = bpy.data.cameras.new("Forge Camera")
    obj = bpy.data.objects.new("Forge Camera", camera)
    scene.collection.objects.link(obj)
    scene.camera = obj
    obj.location = spec["camera"]["location"]
    camera.lens = spec["camera"]["lens"]
    aim(obj, spec["camera"]["target"])
    for item in spec["lights"]:
        light = bpy.data.lights.new("Light_" + item["id"], item["type"])
        light.energy, light.color = item["energy"], item["color"]
        if item["type"] == "AREA":
            light.shape, light.size = "DISK", item["size"]
        obj = bpy.data.objects.new(light.name, light)
        scene.collection.objects.link(obj)
        obj.location = item["location"]
        aim(obj, item["target"])
    scene.frame_set(1)
    bpy.context.view_layer.update()

def publish_scene():
    scene = bpy.context.scene
    scene.frame_set(scene.frame_start)
    progress("saving", 0.48)
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "scene.blend"), check_existing=False)
    progress("exporting_preview", 0.55)
    bpy.ops.export_scene.gltf(filepath=str(output / "preview.glb"), export_format="GLB", export_animations=True, export_frame_range=True, export_apply=True, export_cameras=False, export_lights=False, export_extras=True)
    progress("preview_ready", 0.65, preview=True)

def render_frames(options):
    if not options["enabled"]:
        return []
    scene = bpy.context.scene
    scene.render.engine = options["engine"]
    if options["engine"] == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = options["samples"]
        scene.cycles.use_denoising = True
    scene.render.resolution_x = options["width"]
    scene.render.resolution_y = options["height"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    results = []
    for index, frame in enumerate(options["frames"]):
        if frame > scene.frame_end:
            raise ValueError(f"Frame {frame} exceeds scene.frame_end {scene.frame_end}")
        progress("rendering", 0.65 + 0.3 * index / len(options["frames"]), frame=frame, preview=(output / "preview.glb").exists())
        scene.frame_set(frame)
        name = f"render_{frame:05d}.png"
        scene.render.filepath = str(output / name)
        bpy.ops.render.render(write_still=True)
        results.append(name)
    return results

def main():
    progress("starting", 0.02)
    kind = request["kind"]
    if kind == "build":
        build_scene(request["scene"])
        write_json("scene.json", request["scene"])
    elif kind == "restore":
        base = Path(request["restore_path"])
        bpy.ops.wm.open_mainfile(filepath=str(base / "scene.blend"))
        if (base / "scene.json").exists():
            write_json("scene.json", json.loads((base / "scene.json").read_text(encoding="utf-8")))
    else:
        if request.get("base_blend"):
            bpy.ops.wm.open_mainfile(filepath=request["base_blend"])
        if kind == "python":
            exec(compile(request["code"], "<trusted-ai-script>", "exec"), {"bpy": bpy, "__name__": "__main__", "output_dir": str(output)})
    if kind != "render":
        publish_scene()
    renders = render_frames(request["render"])
    scene = bpy.context.scene
    objects = [{"name": o.name, "type": o.type, "vertices": len(o.data.vertices) if o.type == "MESH" else 0} for o in scene.objects]
    write_json("manifest.json", {"blender_version": bpy.app.version_string, "objects": objects, "object_count": len(objects), "fps": scene.render.fps, "frame_start": scene.frame_start, "frame_end": scene.frame_end, "renders": renders, "preview": "preview.glb" if kind != "render" else None, "blend": "scene.blend" if kind != "render" else None})
    progress("complete", 1, preview=(output / "preview.glb").exists())

try:
    main()
except Exception:
    traceback.print_exc()
    progress("failed", 0)
    raise
