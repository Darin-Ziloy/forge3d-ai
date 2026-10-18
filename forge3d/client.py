import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from .config import ROOT, data_dir, hidden_flags

class Client:
    def __init__(self, port=None):
        self.port = port or int(os.environ.get("FORGE3D_PORT", "8765"))
        self.url = f"http://127.0.0.1:{self.port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, path, body=None):
        headers = {}
        if body is not None:
            headers = {"Content-Type": "application/json", "Authorization": "Bearer " + (data_dir() / "token").read_text(encoding="ascii").strip()}
        request = urllib.request.Request(self.url + path, data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with self.opener.open(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode("utf-8")) from error

    def ensure(self, allow_python=False):
        try:
            health = self.request("/api/health")
            if health.get("service") != "forge3d":
                raise RuntimeError("Port is occupied by another service")
            if allow_python and not health["allow_python"]:
                raise RuntimeError("Restart service with --allow-python to enable trusted scripting")
            return health
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        data = data_dir()
        data.mkdir(parents=True, exist_ok=True)
        executable = sys.executable
        if os.name == "nt":
            pythonw = os.path.join(os.path.dirname(executable), "pythonw.exe")
            if os.path.exists(pythonw):
                executable = pythonw
        args = [executable, "-m", "forge3d", "--port", str(self.port), "serve"]
        if allow_python:
            args.append("--allow-python")
        with (data / "service.log").open("ab") as log:
            subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=hidden_flags(), start_new_session=os.name != "nt")
        for _ in range(100):
            try:
                return self.request("/api/health")
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.1)
        raise RuntimeError(f"Service did not start. Read {data / 'service.log'}")

    def wait(self, job, timeout=600):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.request("/api/jobs/" + job)
            if status["status"] not in {"queued", "running"}:
                return status
            time.sleep(0.5)
        raise TimeoutError(f"Job {job} still running; poll it later")

    def stop(self):
        result = self.request("/api/shutdown", {})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                self.request("/api/health")
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                return result
            time.sleep(0.1)
        raise RuntimeError("Service is taking longer to stop; inspect service.log")
