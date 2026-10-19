import hmac
import json
import mimetypes
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from pydantic import ValidationError
from .engine import Engine, Conflict
from .schema import BuildRequest, PatchRequest
from .storage import safe_id, within, open_archive

class Server(ThreadingHTTPServer):
    daemon_threads = True

def make_server(data, port=8765, allow_python=False, timeout=600):
    # Bind before touching the queue: a second service must not interrupt existing jobs.
    server = Server(("127.0.0.1", port), Handler)
    try:
        server.engine = Engine(Path(data), allow_python=allow_python, timeout=timeout)
    except Exception:
        server.server_close()
        raise
    return server

class Handler(BaseHTTPRequestHandler):
    server_version = "Forge3D/0.2"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, *_):
        pass

    def _guard(self, write=False):
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "") not in allowed:
            raise PermissionError("Unrecognized Host")
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + host for host in allowed}:
            raise PermissionError("Cross-origin access denied")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise PermissionError("Cross-site access denied")
        if write and not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + self.server.engine.token):
            raise PermissionError("A local service token is required")

    def _json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, file):
        if not file.is_file():
            raise FileNotFoundError(file.name)
        content_type = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
        if file.suffix == ".js":
            content_type = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file.stat().st_size))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        # GLTFLoader's ImageBitmapLoader fetches embedded GLB images via local blob URLs.
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' blob:; worker-src 'self' blob:; frame-ancestors 'none'")
        self.end_headers()
        with file.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                self.wfile.write(chunk)

    def _error(self, error):
        if isinstance(error, (BrokenPipeError, ConnectionResetError)):
            return
        status = 400
        if isinstance(error, PermissionError):
            status = 403
        elif isinstance(error, FileNotFoundError):
            status = 404
        elif isinstance(error, Conflict):
            status = 409
        elif not isinstance(error, (ValueError, KeyError, TypeError, ValidationError)):
            status = 500
        self._json({"error": str(error), "type": type(error).__name__}, status)

    def do_GET(self):
        try:
            self._guard()
            path = unquote(urlparse(self.path).path)
            parts = path.strip("/").split("/")
            engine = self.server.engine
            if path == "/api/health":
                return self._json(engine.health())
            if path == "/api/schema":
                return self._json({"build": BuildRequest.model_json_schema(), "patch": PatchRequest.model_json_schema()})
            if path == "/api/projects":
                return self._json(engine.projects())
            if len(parts) == 3 and parts[:2] == ["api", "projects"]:
                return self._json(engine.project(parts[2]))
            if path == "/api/jobs":
                return self._json(engine.jobs())
            if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                return self._json(engine.job(parts[2]))
            if parts[0] == "artifacts":
                # Whitelist public outputs; never expose request.json, code, tokens, or arbitrary files.
                if len(parts) >= 4 and parts[1] == "jobs":
                    base = engine.job_dir(parts[2])
                    name = "/".join(parts[3:])
                elif len(parts) >= 5 and parts[1] == "projects":
                    project = engine.project(parts[2])
                    if parts[3] not in project["history"]:
                        raise FileNotFoundError("Unknown revision")
                    base = engine.project_dir(parts[2]) / "revisions" / safe_id(parts[3])
                    name = "/".join(parts[4:])
                elif len(parts) == 3 and parts[1] == "exports":
                    filename = parts[2]
                    if not filename.endswith(".zip"):
                        raise ValueError("Expected archive")
                    safe_id(filename[:-4])
                    return self._file(engine.data / "exports" / filename)
                else:
                    raise FileNotFoundError(path)
                import re
                if re.fullmatch(r"(?:Textures/[a-zA-Z0-9_-]+\.png|UV/\d{4}\.svg)", name):
                    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
                    if name not in manifest.get("textures", []) + manifest.get("uv_layouts", []):
                        raise FileNotFoundError("Not a declared output")
                    return self._file(within(base, name))
                if name not in {"scene.blend", "preview.glb", "manifest.json", "scene.json", "scene.fbx", "asset_report.json", "asset_bundle.zip"} and not re.fullmatch(r"render_\d{5,6}\.png", name):
                    raise FileNotFoundError("Not a public artifact")
                return self._file(base / name)
            web = Path(__file__).with_name("web")
            return self._file(within(web, "index.html" if path == "/" else path.lstrip("/")))
        except Exception as error:
            self._error(error)

    def do_POST(self):
        try:
            self._guard(write=True)
            size = int(self.headers.get("Content-Length", 0))
            if size <= 0 or size > 16 * 1024 * 1024:
                raise ValueError("JSON request must be 1 byte–16 MiB")
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            path = urlparse(self.path).path
            parts = path.strip("/").split("/")
            engine = self.server.engine
            if path == "/api/projects":
                result = engine.create_project(body["name"])
            elif path == "/api/open-archive":
                with engine.lock:
                    result = open_archive(engine.data, body["source"])
            elif path == "/api/shutdown":
                result = {"stopping": True}
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            elif len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "cancel":
                result = engine.cancel(parts[2])
            elif len(parts) == 4 and parts[:2] == ["api", "projects"]:
                project, action = parts[2:]
                if action == "build":
                    result = engine.build(project, body)
                elif action == "patch":
                    result = engine.patch(project, body)
                elif action == "assets":
                    result = engine.assets(project, body["source"])
                elif action == "render":
                    result = engine.render(project, body["expected_revision"], body.get("render", {}))
                elif action == "restore":
                    result = engine.restore(project, body["revision"], body["expected_revision"])
                elif action == "python":
                    result = engine.python(project, body.get("expected_revision"), body["code"], body.get("render", {}))
                elif action == "archive":
                    result = archive(engine, project)
                else:
                    raise FileNotFoundError(path)
            else:
                raise FileNotFoundError(path)
            self._json(result)
        except Exception as error:
            self._error(error)

def archive(engine, project):
    import uuid
    with engine.lock:
        root = engine.project_dir(project)
        name = uuid.uuid4().hex + ".zip"
        destination = engine.data / "exports" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
            for file in root.rglob("*"):
                if file.is_file() and file.resolve().is_relative_to(root.resolve()):
                    bundle.write(file, file.relative_to(root).as_posix())
        return {"path": str(destination), "url": f"/artifacts/exports/{name}", "project": project}

def serve(data, port=8765, allow_python=False, timeout=600):
    server = make_server(data, port, allow_python, timeout)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.engine.close()
        server.server_close()
