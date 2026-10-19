"""Durable single-worker queue; every Blender invocation is an isolated transaction."""
import copy
import json
import queue
import secrets
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .config import find_blender, hidden_flags
from .schema import BuildRequest, PatchRequest, RenderOptions, SceneSpec
from .storage import atomic_json, import_asset, read_json, safe_id, within

class Conflict(ValueError):
    pass

class Engine:
    def __init__(self, data: Path, allow_python=False, timeout=600):
        self.data = data.resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self._file_lock = (self.data / ".service.lock").open("a+b")
        try:
            self._file_lock.seek(0)
            if self._file_lock.read(1) == b"":
                self._file_lock.write(b"0")
                self._file_lock.flush()
            self._file_lock.seek(0)
            import os
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._file_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._file_lock.close()
            raise Conflict("Another service is already using this data directory")
        self.allow_python = allow_python
        self.timeout = timeout
        self.lock = threading.RLock()
        self.queue = queue.Queue()
        self.process = None
        self.active = None
        self.closing = False
        token = self.data / "token"
        if not token.exists():
            token.write_text(secrets.token_urlsafe(32), encoding="ascii")
        self.token = token.read_text(encoding="ascii").strip()
        for path in (self.data / "jobs").glob("*/job.json"):
            job = read_json(path)
            if job["status"] in {"queued", "running"}:
                job.update(status="interrupted", error="Service stopped before completion; submit again.")
                atomic_json(path, job)
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def health(self):
        try:
            blender, error = find_blender(), None
        except FileNotFoundError as e:
            blender, error = None, str(e)
        return {"service": "forge3d", "version": "0.2.0", "blender": blender, "error": error, "allow_python": self.allow_python, "active_job": self.active}

    def project_dir(self, project):
        path = self.data / "projects" / safe_id(project)
        if not (path / "project.json").is_file():
            raise FileNotFoundError(f"Unknown project: {project}")
        return path

    def create_project(self, name):
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError("Project name must contain 1–200 characters")
        project = {"id": uuid.uuid4().hex, "name": name.strip(), "revision": None, "history": [], "created": time.time()}
        with self.lock:
            atomic_json(self.data / "projects" / project["id"] / "project.json", project)
        return project

    def projects(self):
        with self.lock:
            return sorted([read_json(p) for p in (self.data / "projects").glob("*/project.json")], key=lambda p: p["created"], reverse=True)

    def project(self, project):
        with self.lock:
            result = read_json(self.project_dir(project) / "project.json")
            if result["revision"]:
                base = self.project_dir(project) / "revisions" / result["revision"]
                result["scene"] = read_json(base / "scene.json") if (base / "scene.json").exists() else None
                result["manifest"] = read_json(base / "manifest.json")
            return result

    def assets(self, project, source):
        with self.lock:
            return import_asset(self.project_dir(project), source)

    def jobs(self, limit=100):
        with self.lock:
            return sorted([read_json(p) for p in (self.data / "jobs").glob("*/job.json")], key=lambda j: j["created"], reverse=True)[:limit]

    def job_dir(self, job):
        path = self.data / "jobs" / safe_id(job)
        if not (path / "job.json").exists():
            raise FileNotFoundError("Unknown job")
        return path

    def job(self, job):
        with self.lock:
            base = self.job_dir(job)
            result = read_json(base / "job.json")
            try:
                result["progress"] = read_json(base / "progress.json")
            except (FileNotFoundError, json.JSONDecodeError, PermissionError):
                pass
            log = base / "blender.log"
            if log.exists():
                with log.open("rb") as stream:
                    stream.seek(max(0, log.stat().st_size - 6000))
                    result["log_tail"] = stream.read().decode("utf-8", errors="replace")
            return result

    def _submit(self, project, kind, expected, payload):
        with self.lock:
            if self.closing:
                raise Conflict("Service is stopping")
            current = self.project(project)
            if current["revision"] != expected:
                raise Conflict("Revision changed. Read project and retry with its current revision.")
            unfinished = [j for j in self.jobs(limit=None) if j["status"] in {"queued", "running"}]
            if len(unfinished) >= 32:
                raise Conflict("Queue is full (32 jobs). Wait for a job to finish.")
            if any(j["project"] == project for j in unfinished):
                raise Conflict("Project already has an unfinished job")
            blender = find_blender()
            job_id = uuid.uuid4().hex
            base = self.data / "jobs" / job_id
            job = {"id": job_id, "project": project, "kind": kind, "status": "queued", "created": time.time(), "base_revision": expected}
            payload.update(kind=kind, output=str(base), assets=str(self.project_dir(project) / "assets"))
            if expected:
                payload["base_blend"] = str(self.project_dir(project) / "revisions" / expected / "scene.blend")
            atomic_json(base / "request.json", payload)
            atomic_json(base / "job.json", job)
            self.queue.put((job_id, blender))
            return job

    def build(self, project, body):
        request = BuildRequest.model_validate(body)
        for material in request.scene.materials:
            for field in ("base_color_texture", "normal_texture", "roughness_texture", "metallic_texture"):
                texture = getattr(material, field)
                if texture:
                    asset = within(self.project_dir(project) / "assets", texture.asset)
                    if not asset.is_file() or asset.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                        raise ValueError(f"Missing or unsupported texture: {texture.asset}")
        for obj in request.scene.objects:
            if obj.type == "import":
                asset = within(self.project_dir(project) / "assets", obj.asset)
                if not asset.is_file() or asset.suffix.lower() not in {".glb", ".gltf", ".obj", ".stl", ".fbx"}:
                    raise ValueError(f"Missing or unsupported asset: {obj.asset}")
        return self._submit(project, "build", request.expected_revision, request.model_dump(mode="json"))

    def patch(self, project, body):
        request = PatchRequest.model_validate(body)
        with self.lock:
            current = self.project(project)
            if not current.get("scene"):
                raise ValueError("No declarative scene to patch; submit a full scene or use Python mode")
            scene = copy.deepcopy(current["scene"])
            objects = {o["id"]: o for o in scene["objects"] if o["id"] not in request.delete_objects}
            objects.update({o.id: o.model_dump(mode="json") for o in request.upsert_objects})
            materials = {m["id"]: m for m in scene["materials"]}
            materials.update({m.id: m.model_dump(mode="json") for m in request.upsert_materials})
            scene.update(objects=list(objects.values()), materials=list(materials.values()))
            return self.build(project, {"scene": scene, "expected_revision": request.expected_revision, "render": request.render.model_dump()})

    def restore(self, project, revision, expected):
        with self.lock:
            current = self.project(project)
            if revision not in current["history"]:
                raise ValueError("Revision does not belong to this project")
            return self._submit(project, "restore", expected, {"restore_path": str(self.project_dir(project) / "revisions" / revision), "render": RenderOptions().model_dump()})

    def render(self, project, expected, options):
        if not expected:
            raise ValueError("Build a scene first")
        render = RenderOptions.model_validate(options)
        render.enabled = True
        return self._submit(project, "render", expected, {"render": render.model_dump()})

    def python(self, project, expected, code, render):
        if not self.allow_python:
            raise PermissionError("Python mode is disabled. Start service with --allow-python for trusted agents.")
        if not isinstance(code, str) or not code.strip() or len(code) > 200000:
            raise ValueError("Expected 1–200000 characters of Python")
        return self._submit(project, "python", expected, {"code": code, "render": RenderOptions.model_validate(render).model_dump()})

    def cancel(self, job_id):
        with self.lock:
            path = self.job_dir(job_id) / "job.json"
            job = read_json(path)
            if job["status"] in {"queued", "running"}:
                job.update(status="cancelled", finished=time.time())
                atomic_json(path, job)
                if self.active == job_id and self.process:
                    self.process.terminate()
            return job

    def close(self):
        with self.lock:
            self.closing = True
            for job in self.jobs(limit=None):
                if job["status"] in {"queued", "running"}:
                    self.cancel(job["id"])
            self.queue.put(None)
        self.thread.join(timeout=10)
        self._file_lock.close()

    def _loop(self):
        while (item := self.queue.get()) is not None:
            job_id, blender = item
            base = self.job_dir(job_id)
            try:
                with self.lock:
                    job = read_json(base / "job.json")
                    if job["status"] == "cancelled":
                        continue
                    self.active = job_id
                    job.update(status="running", started=time.time())
                    atomic_json(base / "job.json", job)
                    log = (base / "blender.log").open("wb")
                    command = [blender, "--background", "--factory-startup", "--disable-autoexec", "--threads", "2", "--python-exit-code", "1", "--python", str(Path(__file__).with_name("blender_worker.py")), "--", str(base / "request.json")]
                    try:
                        self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=hidden_flags())
                    except Exception:
                        log.close()
                        raise
                try:
                    code = self.process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
                    raise RuntimeError(f"Job exceeded {self.timeout}s timeout")
                finally:
                    log.close()
                with self.lock:
                    job = read_json(base / "job.json")
                    if job["status"] == "cancelled":
                        continue
                    if code != 0 or not (base / "manifest.json").exists():
                        raise RuntimeError(f"Blender failed (exit {code}); inspect log_tail")
                    if job["kind"] != "render":
                        self._commit(job, base)
                    job.update(status="succeeded", finished=time.time(), manifest=read_json(base / "manifest.json"))
                    atomic_json(base / "job.json", job)
            except Exception as error:
                with self.lock:
                    job = read_json(base / "job.json")
                    if job["status"] != "cancelled":
                        job.update(status="failed", error=str(error), finished=time.time())
                        atomic_json(base / "job.json", job)
            finally:
                with self.lock:
                    self.process = None
                    self.active = None

    def _commit(self, job, base):
        import shutil
        project_dir = self.project_dir(job["project"])
        project = read_json(project_dir / "project.json")
        if project["revision"] != job["base_revision"]:
            raise Conflict("Project changed while job was running")
        destination = project_dir / "revisions" / job["id"]
        destination.mkdir(parents=True)
        for name in ["scene.blend", "preview.glb", "scene.json", "manifest.json", "scene.fbx", "asset_report.json", "asset_bundle.zip"]:
            if (base / name).exists():
                shutil.copy2(base / name, destination / name)
        for directory in ("Textures", "UV"):
            if (base / directory).is_dir():
                shutil.copytree(base / directory, destination / directory)
        for file in base.glob("render_*.png"):
            shutil.copy2(file, destination / file.name)
        if not (destination / "scene.blend").exists() or not (destination / "preview.glb").exists():
            raise RuntimeError("Worker did not produce scene.blend and preview.glb")
        project.update(revision=job["id"], updated=time.time())
        project["history"].append(job["id"])
        atomic_json(project_dir / "project.json", project)
