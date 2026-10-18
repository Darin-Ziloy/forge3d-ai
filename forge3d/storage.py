import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(25):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 24:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(0.02)

def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def safe_id(value):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", value):
        raise ValueError("Invalid identifier")
    return value

def within(root: Path, relative: str):
    if "\\" in relative or ":" in relative:
        raise ValueError("Expected a relative path with forward slashes")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Path escapes its project")
    return path

def import_asset(project_dir: Path, source: str):
    """Copy explicitly selected local model and supported dependencies into project."""
    source = Path(source).resolve()
    ext = source.suffix.lower()
    if ext not in {".glb", ".gltf", ".obj", ".stl", ".fbx"}:
        raise ValueError("Supported imports: GLB, glTF, OBJ, STL, FBX")
    if not source.is_file():
        raise FileNotFoundError(source)
    files = {source}

    def add_relative(uri):
        if uri.startswith("data:"):
            return
        if urlparse(uri).scheme or uri.startswith(("/", "\\")):
            raise ValueError("Only local, relative asset dependencies are supported")
        dependency = within(source.parent, unquote(uri))
        if not dependency.is_file():
            raise ValueError(f"Missing model dependency: {uri}")
        files.add(dependency)

    if ext == ".gltf":
        gltf = read_json(source)
        for entry in gltf.get("buffers", []) + gltf.get("images", []):
            if "uri" in entry:
                add_relative(entry["uri"])
    if ext == ".obj":
        for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("mtllib "):
                add_relative(line.strip()[7:].strip())
        for mtl in list(files):
            if mtl.suffix.lower() == ".mtl":
                for line in mtl.read_text(encoding="utf-8", errors="replace").splitlines():
                    parts = line.strip().split(maxsplit=1)
                    if len(parts) == 2 and (parts[0].lower().startswith("map_") or parts[0].lower() in {"bump", "disp", "decal", "norm"}):
                        if parts[1].startswith("-"):
                            raise ValueError("MTL texture options are not supported; use a self-contained GLB")
                        add_relative((mtl.parent.relative_to(source.parent) / parts[1]).as_posix())
    if ext == ".fbx":
        texture_dir = source.with_suffix(".fbm")
        if texture_dir.is_dir():
            for file in texture_dir.rglob("*"):
                if file.is_file():
                    if not file.resolve().is_relative_to(source.parent):
                        raise ValueError("Texture path escapes model directory")
                    files.add(file)
    if len(files) > 2000 or sum(f.stat().st_size for f in files) > 512 * 1024 * 1024:
        raise ValueError("Asset exceeds 512 MiB / 2000 files import limit")
    asset_id = uuid.uuid4().hex
    destination = project_dir / "assets" / asset_id
    destination.mkdir(parents=True)
    try:
        for file in files:
            target = destination / file.relative_to(source.parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
    except Exception:
        shutil.rmtree(destination)
        raise
    return {"asset": f"{asset_id}/{source.name}", "files": len(files), "bytes": sum(f.stat().st_size for f in files)}

def open_archive(data: Path, source: str):
    """Restore a portable archive as a new independent project; never overwrite one."""
    import stat
    import time
    import zipfile
    from .schema import SceneSpec
    with zipfile.ZipFile(Path(source).resolve()) as archive:
        entries = archive.infolist()
        if len(entries) > 10000 or sum(e.file_size for e in entries) > 2 * 1024**3:
            raise ValueError("Archive exceeds 2 GiB / 10000 entries limit")
        project = json.loads(archive.read("project.json"))
        if not isinstance(project.get("name"), str) or not 1 <= len(project["name"]) <= 200:
            raise ValueError("Invalid project name in archive")
        history = project.get("history", [])
        if not isinstance(history, list) or len(history) != len(set(history)):
            raise ValueError("Invalid revision history")
        for revision in history:
            safe_id(revision)
            for name in ["scene.blend", "preview.glb", "manifest.json"]:
                archive.getinfo(f"revisions/{revision}/{name}")
            scene_path = f"revisions/{revision}/scene.json"
            if scene_path in archive.namelist():
                SceneSpec.model_validate_json(archive.read(scene_path))
        if project.get("revision") is not None and project["revision"] not in history:
            raise ValueError("Current revision is missing from archive")
        project_id = uuid.uuid4().hex
        root = data / "projects" / project_id
        staging = data / "imports" / project_id
        staging.mkdir(parents=True)
        try:
            seen = set()
            for entry in entries:
                name = entry.filename
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError("Archive links are not allowed")
                if name != "project.json" and not name.startswith(("assets/", "revisions/")):
                    raise ValueError("Unexpected archive path")
                target = within(staging, name)
                # Windows filenames are case-insensitive; reject ambiguous entries everywhere.
                normalized = str(target).lower()
                if normalized in seen:
                    raise ValueError("Duplicate archive path")
                seen.add(normalized)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as stream, target.open("wb") as destination:
                        shutil.copyfileobj(stream, destination)
            project = {"id": project_id, "name": project["name"] + " (imported)" if len(project["name"]) < 185 else project["name"], "revision": project.get("revision"), "history": history, "created": time.time()}
            atomic_json(staging / "project.json", project)
            root.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, root)
        except Exception:
            shutil.rmtree(staging)
            raise
        return project
