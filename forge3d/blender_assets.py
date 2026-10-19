"""Blender-only texture, UV, bake and game-asset output helpers."""
import math
from pathlib import Path
import re
import zipfile

import bpy

TEXTURE_SLOTS = {
    "base_color_texture": ("Base Color", "sRGB"),
    "normal_texture": ("Normal", "Non-Color"),
    "roughness_texture": ("Roughness", "Non-Color"),
    "metallic_texture": ("Metallic", "Non-Color"),
}


def active_only(obj):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def apply_uv(obj, spec):
    mode = spec.get("mode", "preserve")
    if mode == "preserve":
        return
    active_only(obj)
    # Imported instances can share mesh data: never alter another instance's UVs.
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    layer = obj.data.uv_layers.get(spec["name"]) or obj.data.uv_layers.new(name=spec["name"])
    obj.data.uv_layers.active = layer
    layer.active_render = True
    if mode == "explicit":
        coordinates = spec["coordinates"]
        if len(coordinates) != len(obj.data.polygons):
            raise ValueError("Explicit UV face count does not match mesh")
        for face, uvs in zip(obj.data.polygons, coordinates):
            if len(face.loop_indices) != len(uvs):
                raise ValueError("Explicit UV corner count does not match mesh")
            for loop, uv in zip(face.loop_indices, uvs):
                layer.data[loop].uv = uv
    else:
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.smart_project(angle_limit=math.radians(spec["angle_limit"]),
                island_margin=spec["island_margin"], margin_method="FRACTION", scale_to_bounds=True)
        finally:
            bpy.ops.object.mode_set(mode="OBJECT")


def connect_image(material, slot, image, uv_name="UVMap", strength=1, interpolation="Linear", extension="REPEAT"):
    nodes, links = material.node_tree.nodes, material.node_tree.links
    shader = nodes.get("Principled BSDF")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image, texture.interpolation, texture.extension = image, interpolation, extension
    uv = nodes.new("ShaderNodeUVMap")
    uv.uv_map = uv_name
    links.new(uv.outputs["UV"], texture.inputs["Vector"])
    if slot == "normal_texture":
        normal = nodes.new("ShaderNodeNormalMap")
        normal.uv_map = uv_name
        normal.inputs["Strength"].default_value = strength
        links.new(texture.outputs["Color"], normal.inputs["Color"])
        links.new(normal.outputs["Normal"], shader.inputs["Normal"])
    else:
        links.new(texture.outputs["Color"], shader.inputs[TEXTURE_SLOTS[slot][0]])
    # glTF multiplies the sampled base color by this factor.
    if slot == "base_color_texture":
        shader.inputs["Base Color"].default_value = (1, 1, 1, 1)
    return texture


def material_textures(material, item, assets):
    root = Path(assets).resolve()
    for slot, (_, color_space) in TEXTURE_SLOTS.items():
        spec = item.get(slot)
        if not spec:
            continue
        path = (root / spec["asset"]).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("Texture must be a project PNG/JPEG asset")
        image = bpy.data.images.load(str(path), check_existing=False)
        if min(image.size) < 1 or max(image.size) > 8192:
            raise ValueError("Texture dimensions must be between 1 and 8192 pixels")
        image.colorspace_settings.name = color_space
        image.name = item["id"] + "_" + slot.removesuffix("_texture")
        connect_image(material, slot, image, spec["uv_map"], item["normal_strength"], spec["interpolation"], spec["extension"])


def bake_assets(specs, objects, progress):
    sources = set()
    for index, spec in enumerate(specs):
        low = objects[spec["low"]]
        high = [objects[name] for name in spec["high"]]
        if not low.data.uv_layers.active:
            raise ValueError(f"Bake target {low.name} needs UVs; use uv.mode=smart or explicit")
        active_only(low)
        # Bake results use one independent material, so existing shared materials stay intact.
        mat = bpy.data.materials.new(low.name + "_Baked")
        mat.use_nodes = True
        mat.node_tree.nodes.get("Principled BSDF").inputs["Roughness"].default_value = 0.55
        low.data.materials.clear()
        low.data.materials.append(mat)
        for face in low.data.polygons:
            face.material_index = 0
        for obj in high:
            obj.hide_set(False)
            obj.hide_render = False
            obj.select_set(True)
        scene = bpy.context.scene
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 16
        baked = []
        for mode in (["albedo", "normal"] if spec["mode"] == "both" else [spec["mode"]]):
            progress("baking", 0.41 + 0.05 * index / max(1, len(specs)), object=low.name, map=mode)
            image = bpy.data.images.new(low.name + ("_Albedo" if mode == "albedo" else "_Normal"),
                width=spec["size"], height=spec["size"], alpha=False)
            image.colorspace_settings.name = "sRGB" if mode == "albedo" else "Non-Color"
            node = mat.node_tree.nodes.new("ShaderNodeTexImage")
            node.image = image
            mat.node_tree.nodes.active = node
            result = bpy.ops.object.bake(type="DIFFUSE" if mode == "albedo" else "NORMAL",
                pass_filter={"COLOR"} if mode == "albedo" else set(), use_selected_to_active=True,
                normal_space="TANGENT", margin=spec["margin"], use_clear=True,
                cage_extrusion=spec["cage_extrusion"], max_ray_distance=spec["max_ray_distance"])
            if "FINISHED" not in result:
                raise RuntimeError(f"Bake failed for {low.name}: {mode}")
            mat.node_tree.nodes.remove(node)
            baked.append(("base_color_texture" if mode == "albedo" else "normal_texture", image))
        for slot, image in baked:
            connect_image(mat, slot, image, low.data.uv_layers.active.name)
        sources.update(high)
    for obj in sources:
        bpy.data.objects.remove(obj, do_unlink=True)


def linked_images(material):
    """Find image nodes upstream of the material output, excluding disconnected bake targets."""
    if not material or not material.use_nodes:
        return []
    pending = [n for n in material.node_tree.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output]
    visited, images = set(), []
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)
        if node.type == "TEX_IMAGE" and node.image:
            images.append(node)
        for socket in node.inputs:
            pending.extend(link.from_node for link in socket.links)
    return images


def texture_uv_name(node, mesh):
    vector = node.inputs.get("Vector")
    if vector and vector.is_linked:
        source = vector.links[0].from_node
        if source.type == "UVMAP":
            return source.uv_map or (mesh.uv_layers.active.name if mesh.uv_layers.active else None)
        # Imported glTF may include mapping nodes; active UV is still checked below.
    return mesh.uv_layers.active.name if mesh.uv_layers.active else None


def collect_asset_outputs(output, checks=None):
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    materials, images, records, warnings = set(), {}, [], []
    total_tris, draw_calls = 0, 0
    (output / "Textures").mkdir(exist_ok=True)
    (output / "UV").mkdir(exist_ok=True)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for number, obj in enumerate(meshes):
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            tris = len(mesh.loop_triangles)
            total_tris += tris
            used_slots = {face.material_index for face in mesh.polygons}
            object_materials = [slot.material for i, slot in enumerate(obj.material_slots) if i in used_slots and slot.material]
            materials.update(object_materials)
            draw_calls += max(1, len(object_materials))
            nodes = [node for mat in object_materials for node in linked_images(mat)]
            for node in nodes:
                name = texture_uv_name(node, mesh)
                if not name or not mesh.uv_layers.get(name):
                    raise ValueError(f"Textured mesh {obj.name} is missing UV map {name!r}")
                image = node.image
                # size forces lazy image loading after a color-space change.
                if min(image.size) < 1:
                    raise ValueError(f"Missing image data: {image.name}")
                if image not in images:
                    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", image.name)[:80]
                    path = f"Textures/{len(images):03d}_{slug}.png"
                    image.filepath_raw = str(output / path)
                    image.file_format = "PNG"
                    image.save()
                    image.pack()
                    image.filepath = "//" + path
                    images[image] = {"name": image.name, "path": path, "width": image.size[0], "height": image.size[1], "color_space": image.colorspace_settings.name}
            layer = mesh.uv_layers.active
            degenerate = 0
            if layer:
                polygons = []
                for face in mesh.polygons:
                    uv = [tuple(layer.data[i].uv) for i in face.loop_indices]
                    area = abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(uv, uv[1:]+uv[:1]))) / 2
                    degenerate += area < 1e-12
                    points = " ".join(f"{u*1024:.4f},{(1-v)*1024:.4f}" for u,v in uv)
                    polygons.append(f'<polygon points="{points}"/>')
                layout = f"UV/{number:04d}.svg"
                (output / layout).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><rect width="1024" height="1024" fill="#14201b"/><g fill="none" stroke="#c4ef99" stroke-width="1">'+"".join(polygons)+"</g></svg>", encoding="utf-8")
            else:
                layout = None
            if nodes and degenerate:
                raise ValueError(f"Textured mesh {obj.name} has {degenerate} collapsed UV faces")
            albedo = any(mat.use_nodes and (shader := mat.node_tree.nodes.get("Principled BSDF")) and
                shader.inputs["Base Color"].is_linked and shader.inputs["Base Color"].links[0].from_node.type == "TEX_IMAGE"
                for mat in object_materials)
            records.append({"name": obj.name, "triangles": tris, "materials": len(object_materials),
                "uv_maps": [u.name for u in mesh.uv_layers], "uv_layout": layout,
                "degenerate_uv_faces": degenerate, "image_textures": [images[n.image]["path"] for n in nodes], "albedo_texture": bool(albedo)})
        finally:
            evaluated.to_mesh_clear()
    for image in images.values():
        if any(n & (n-1) for n in (image["width"],image["height"])):
            warnings.append(f"Non-power-of-two image: {image['path']}")
    if checks:
        if total_tris > checks["max_tris"]:
            raise ValueError(f"Triangle budget exceeded: {total_tris} > {checks['max_tris']}")
        if checks["target_use"] == "packaging":
            if not 1 <= len(meshes) <= 2 or not 1 <= len(materials) <= 2 or not all(r["albedo_texture"] for r in records):
                raise ValueError("Packaging requires 1–2 meshes/materials and an albedo UV texture on every mesh")
    return {"triangles": total_tris, "mesh_count": len(meshes), "material_count": len(materials),
        "draw_call_proxy": draw_calls, "textures": list(images.values()), "objects": records, "warnings": warnings,
        "unity_tested": False, "uv_overlap_checked": False}


def export_fbx(output):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            obj.hide_set(False)
            obj.select_set(True)
    bpy.ops.export_scene.fbx(filepath=str(output / "scene.fbx"), use_selection=True, object_types={"MESH"},
        axis_forward="-Z", axis_up="Y", apply_unit_scale=True, bake_anim=True, path_mode="COPY", embed_textures=True)


def asset_bundle(output, render_names):
    files = [output / name for name in ["scene.blend", "preview.glb", "scene.fbx", "asset_report.json", "scene.json", *render_names] if (output / name).is_file()]
    for directory in ("Textures", "UV"):
        files.extend(p for p in (output / directory).glob("*") if p.is_file())
    with zipfile.ZipFile(output / "asset_bundle.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, file.relative_to(output).as_posix())
