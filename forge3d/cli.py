import argparse
import json
import os
from pathlib import Path
import sys
import webbrowser
from .client import Client
from .config import ROOT, data_dir

def main():
    parser = argparse.ArgumentParser(prog="forge3d")
    parser.add_argument("--port", type=int, default=int(os.environ.get("FORGE3D_PORT", "8765")))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["serve", "start"]:
        command = sub.add_parser(name)
        command.add_argument("--allow-python", action="store_true")
        if name == "serve":
            command.add_argument("--timeout", type=int, default=600)
    for name in ["status", "stop", "viewer", "mcp", "mcp-config", "projects"]:
        sub.add_parser(name)
    demo = sub.add_parser("demo")
    demo.add_argument("--render", action="store_true")
    demo.add_argument("--wait", action="store_true")
    create = sub.add_parser("create")
    create.add_argument("name")
    build = sub.add_parser("build")
    build.add_argument("project")
    build.add_argument("scene", type=Path)
    build.add_argument("--wait", action="store_true")
    imp = sub.add_parser("import")
    imp.add_argument("project")
    imp.add_argument("source", type=Path)
    save = sub.add_parser("save")
    save.add_argument("project")
    reopen = sub.add_parser("open")
    reopen.add_argument("archive", type=Path)
    args = parser.parse_args()
    os.environ["FORGE3D_PORT"] = str(args.port)
    client = Client(args.port)
    if args.command == "serve":
        from .server import serve
        return serve(data_dir(), args.port, args.allow_python, args.timeout)
    if args.command == "mcp":
        from .mcp_server import create_mcp
        create_mcp().run(transport="stdio")
        return
    if args.command == "mcp-config":
        result = {"mcpServers": {"forge3d": {"command": sys.executable, "args": ["-m", "forge3d", "--port", str(args.port), "mcp"], "env": {"PYTHONPATH": str(ROOT), "FORGE3D_DATA": str(data_dir())}}}}
    elif args.command == "stop":
        result = client.stop()
    elif args.command == "start":
        result = client.ensure(allow_python=args.allow_python)
    elif args.command == "status":
        result = client.request("/api/health")
    else:
        client.ensure()
        if args.command == "viewer":
            webbrowser.open(client.url)
            result = {"viewer": client.url}
        elif args.command == "projects":
            result = client.request("/api/projects")
        elif args.command == "create":
            result = client.request("/api/projects", {"name": args.name})
        elif args.command == "import":
            result = client.request(f"/api/projects/{args.project}/assets", {"source": str(args.source.resolve())})
        elif args.command == "save":
            result = client.request(f"/api/projects/{args.project}/archive", {})
        elif args.command == "open":
            result = client.request("/api/open-archive", {"source": str(args.archive.resolve())})
        elif args.command in {"demo", "build"}:
            if args.command == "demo":
                scene = json.loads((ROOT / "examples" / "orbital-bot.json").read_text(encoding="utf-8"))
                project = client.request("/api/projects", {"name": "Orbital / inspection drone"})
            else:
                scene = json.loads(args.scene.read_text(encoding="utf-8"))
                project = client.request("/api/projects/" + args.project)
            result = client.request(f"/api/projects/{project['id']}/build", {"scene": scene, "expected_revision": project["revision"], "render": {"enabled": getattr(args, "render", False)}})
            if args.wait:
                result = client.wait(result["id"])
            result["viewer"] = client.url + "/?project=" + project["id"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if isinstance(result, dict) and result.get("status") in {"failed", "interrupted", "cancelled"}:
        sys.exit(1)

if __name__ == "__main__":
    main()
