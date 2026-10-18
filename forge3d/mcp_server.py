"""MCP is a thin adapter; all clients share the same durable local service."""
import base64
import webbrowser
from mcp.server import MCPServer
from mcp.types import CallToolResult, ImageContent
from .client import Client
from .schema import SceneSpec, ObjectSpec, Material, RenderOptions

def create_mcp():
    app = MCPServer("Forge3D", version="0.1.0", instructions="Local 3D workspace. Call capabilities, create/list projects, import assets, then build_scene. Units meters; Z up; Euler rotations in degrees. Mutations return job IDs immediately: poll job_status until succeeded before further edits. Read project for current revision; pass expected_revision to avoid overwrites. Use patch_scene for small batches. View renders to inspect your work. Local Python is opt-in and not sandboxed.")
    client = Client()

    def call(path, body=None):
        client.ensure()
        return client.request(path, body)

    @app.tool()
    def capabilities() -> dict:
        """Inspect engine availability, units, formats and the complete scene JSON schema."""
        return {"health": call("/api/health"), "scene_schema": SceneSpec.model_json_schema(), "import_formats": ["glb", "gltf", "obj", "stl", "fbx"], "export_formats": ["blend", "glb", "png", "project.zip"], "units": "meters, Z-up, degrees", "viewer": client.url}

    @app.tool()
    def list_projects() -> list[dict]:
        """List saved projects, including their current revision and history."""
        return call("/api/projects")

    @app.tool()
    def create_project(name: str) -> dict:
        """Create a persistent project. It is saved automatically after every successful build."""
        return call("/api/projects", {"name": name})

    @app.tool()
    def inspect_project(project_id: str) -> dict:
        """Read current scene, revision, object inventory and history before editing."""
        return call(f"/api/projects/{project_id}")

    @app.tool()
    def import_asset(project_id: str, source_path: str) -> dict:
        """Copy a local GLB/glTF/OBJ/STL/FBX into this project. Add an object of type import with the returned asset string to place it in the scene. GLB is the most portable format."""
        return call(f"/api/projects/{project_id}/assets", {"source": source_path})

    @app.tool()
    def build_scene(project_id: str, scene: SceneSpec, expected_revision: str | None = None, render: RenderOptions | None = None) -> dict:
        """Replace the scene declaratively in one transaction. First build: expected_revision=null; otherwise pass the current revision. Returns queued job, not a finished model."""
        return call(f"/api/projects/{project_id}/build", {"scene": scene.model_dump(mode="json"), "expected_revision": expected_revision, "render": (render or RenderOptions()).model_dump()})

    @app.tool()
    def patch_scene(project_id: str, expected_revision: str, upsert_objects: list[ObjectSpec] | None = None, delete_objects: list[str] | None = None, upsert_materials: list[Material] | None = None) -> dict:
        """Batch object/material changes. Upsert replaces the entire object with that ID; include fields you wish to retain. Parent references must remain valid."""
        return call(f"/api/projects/{project_id}/patch", {"expected_revision": expected_revision, "upsert_objects": [o.model_dump(mode="json") for o in upsert_objects or []], "delete_objects": delete_objects or [], "upsert_materials": [m.model_dump(mode="json") for m in upsert_materials or []]})

    @app.tool()
    def job_status(job_id: str) -> dict:
        """Read status, stage, Blender log and output manifest. Poll until succeeded, failed, cancelled or interrupted."""
        return call(f"/api/jobs/{job_id}")

    @app.tool()
    def cancel_job(job_id: str) -> dict:
        """Cancel queued/running work. Last successful project revision is retained."""
        return call(f"/api/jobs/{job_id}/cancel", {})

    @app.tool()
    def render_frames(project_id: str, expected_revision: str, options: RenderOptions | None = None) -> dict:
        """Render selected frames as PNGs. Cycles CPU is default; use a small sample count for quick inspection. Returns job ID."""
        return call(f"/api/projects/{project_id}/render", {"expected_revision": expected_revision, "render": (options or RenderOptions(enabled=True)).model_dump()})

    @app.tool()
    def view_render(job_id: str, frame: int = 1) -> CallToolResult:
        """Return a rendered PNG as MCP image content so a vision-capable AI can inspect it."""
        job = call(f"/api/jobs/{job_id}")
        name = f"render_{frame:05d}.png"
        if job["status"] != "succeeded" or name not in job.get("manifest", {}).get("renders", []):
            raise ValueError("Requested render is not available; inspect job_status")
        with client.opener.open(client.url + f"/artifacts/jobs/{job_id}/{name}", timeout=30) as response:
            data = response.read()
        return CallToolResult(content=[ImageContent(type="image", data=base64.b64encode(data).decode(), mimeType="image/png")])

    @app.tool()
    def restore_revision(project_id: str, revision: str, expected_revision: str) -> dict:
        """Restore a saved revision as a NEW revision, keeping the complete history."""
        return call(f"/api/projects/{project_id}/restore", {"revision": revision, "expected_revision": expected_revision})

    @app.tool()
    def save_project_archive(project_id: str) -> dict:
        """Save a portable ZIP containing project metadata, versions, packed .blend files, previews and imported assets. Normal projects are already autosaved."""
        return call(f"/api/projects/{project_id}/archive", {})

    @app.tool()
    def open_project_archive(source_path: str) -> dict:
        """Open a Forge3D project ZIP as a new project, preserving versions and assets. Existing projects are never overwritten."""
        return call("/api/open-archive", {"source": source_path})

    @app.tool()
    def execute_blender_python(project_id: str, code: str, expected_revision: str | None = None) -> dict:
        """Advanced trusted-only mode, disabled by default. Execute bpy Python on a copy of the current scene (rigging, Geometry Nodes, UVs, simulations, custom exports). Has the user's OS privileges; NOT a sandbox. Success creates a new .blend/GLB revision. Declarative patches are unavailable afterward; use Python or rebuild."""
        return call(f"/api/projects/{project_id}/python", {"code": code, "expected_revision": expected_revision})

    @app.tool()
    def open_viewer(project_id: str | None = None) -> dict:
        """Open the human viewer with orbit, pan, zoom, animation timeline, progress and renders."""
        client.ensure()
        url = client.url + ("/?project=" + project_id if project_id else "/")
        webbrowser.open(url)
        return {"url": url}

    return app
