# User guide

Forge3D AI is a local workspace for AI-driven 3D creation. The service runs Blender in background processes, exposes MCP and JSON interfaces, and serves a small Three.js viewer. All application-owned UI text, documentation, comments, and examples are maintained in English.

## Installation

Use Windows 10/11 x64, Python 3.11+, and installed or portable Blender. The verified stack is Windows 10 build 19044, Python 3.14.4, and Blender 5.2.2 LTS. Other combinations need their own validation.

Run `Setup.ps1` from the project directory. It creates a local virtual environment, installs the editable Python package, prepares viewer dependencies if necessary, and writes `mcp-config.json` for this directory. Node.js/npm is needed only to prepare missing viewer dependencies.

If PowerShell policy prevents running the script, execute these commands manually; no system policy change is necessary:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
npm.cmd ci --ignore-scripts --no-audit --no-fund
npm.cmd run vendor
.\.venv\Scripts\python.exe -m forge3d mcp-config
```

Blender discovery checks `PATH`, the repository's `runtime/` directory, standard Blender Foundation installations, and the standard Steam installation directory. Custom Steam libraries are not scanned automatically. Set `BLENDER_PATH` to the desired executable before starting the service when necessary.

Internet access is needed for dependency installation. Runtime uses local assets and has no CDN, external model API, or telemetry requirement. The AI client itself may be local or cloud-hosted.

## Start, view, and stop

- `Start-Forge3D.cmd` starts a hidden local service and opens the viewer at `http://127.0.0.1:8765`.
- `Start-Demo.cmd` creates a new **Orbital / inspection drone** project, including animation and a render. Each invocation creates another project.
- `Stop-Forge3D.cmd` stops the service and cancels unfinished jobs.

The full Blender UI is not required. Closing the viewer does not stop the service. Blender starts for a job and exits afterward; it does not remain resident while idle. Forge3D does not add itself to Windows startup.

In the viewer, use left drag to orbit, right drag to pan, the scroll wheel to zoom, and **F** to frame the model. Play/pause, rewind, the timeline slider, wireframe, automatic orbit, revision selection, the object list, and a render dialog are also available.

## MCP connection and agent workflow

Generate configuration with `python -m forge3d mcp-config` using the project's virtual environment. Add the resulting `mcpServers.forge3d` entry to the host's MCP configuration; exact host configuration formats can vary. The generated file contains installation-specific paths and is intentionally excluded from Git.

The official MCP SDK communicates over stdio. The first tool call starts the shared local service if needed. Multiple clients share its queue; `expected_revision` prevents stale edits from overwriting newer work. Cloud-only hosts cannot directly reach your loopback interface and need a local bridge. Remote MCP hosting is not implemented in 0.1.

Recommended agent cycle:

1. Call `capabilities` to inspect engine availability and the scene schema.
2. Create a project, or list projects and inspect an existing one.
3. Call `import_asset` for any existing local model files.
4. Submit a complete scene with `build_scene`; keep the returned job ID.
5. Poll `job_status` until it reaches a terminal state. Do not resubmit the same job while it runs.
6. Read the current project revision and scene with `inspect_project`.
7. Use `patch_scene` for batches of edits, or `render_frames` and `view_render` for visual feedback.
8. Save a portable ZIP with `save_project_archive`; reopen it with `open_project_archive`.

Successful jobs return manifests and files, while failed jobs return error details and a log tail. Vision-capable clients can receive a PNG through native MCP image content.

## Scene conventions

Distances are **meters**, the up axis is **Z**, and Euler rotations are **degrees**. Child transforms are relative to their parent. Object and material references use stable IDs.

Default primitive sizes before `scale`: cube side 2; sphere radius 1; cylinder/cone radius 1 and height 2; plane 2 x 2; torus major radius 1 and minor radius 0.08. The cone is pointed by default. Use a custom mesh or trusted Python for more specific geometry.

Supported modifiers: bevel, subdivision, solidify, mirror, and decimate. PBR material fields include color, metallic, roughness, and emission. Transform animation uses position, rotation, and scale keyframes with linear interpolation.

`patch_scene.upsert_objects` replaces the whole object with that ID, so include fields you want to preserve. Deleting a parent requires deleting its children or updating their parent references. To change scene settings such as camera, lights, fps, or world color, read the current scene and submit a modified complete scene.

`preview_hidden` hides an object in the human viewer while retaining it in exported geometry and final Blender renders. This is useful for studio backdrops. The viewer's lighting differs from Blender's render lighting.

## Importing models

```powershell
.\.venv\Scripts\python.exe -m forge3d create 'My project'
.\.venv\Scripts\python.exe -m forge3d import PROJECT_ID 'C:\Models\robot.glb'
```

Import copies the selected model and supported dependencies into the project and returns an `asset` reference. It does not place the model in the scene by itself. Add an import object:

```json
{
  "name": "Robot scene",
  "objects": [{
    "id": "robot",
    "type": "import",
    "asset": "RETURNED_ASSET_ID/robot.glb",
    "location": [0, 0, 0],
    "scale": [1, 1, 1]
  }]
}
```

Save the JSON and run `forge3d build PROJECT_ID scene.json --wait` using the project's Python environment, or submit it through MCP.

| Format | Notes |
|---|---|
| GLB | Recommended portable exchange format for geometry, materials, and animation |
| glTF | Relative local buffer/image dependencies within the source directory are copied |
| OBJ + MTL | Geometry and supported material/texture dependencies; complex MTL texture options are not supported |
| STL | Geometry only |
| FBX | Embedded textures and a neighboring `.fbm` directory are supported; pack externally located textures first |

Network resource URIs and references escaping the source directory are rejected. Asset import is limited to 512 MiB and 2,000 files. Arbitrary external `.blend` import is not a standard command; use GLB/FBX or trusted Python mode.

## Saving, exporting, and reopening

Every successful build automatically saves a project revision. Standard outputs are `.blend`, `.glb`, and optional `.png` frames. Download model files from the viewer. FBX, OBJ, and STL export are not standard commands in this version.

```powershell
.\.venv\Scripts\python.exe -m forge3d save PROJECT_ID
.\.venv\Scripts\python.exe -m forge3d open 'C:\Archives\project.zip'
```

`save` returns the archive path. `open` creates a new independent project ID while retaining assets and history; it never overwrites an existing project. Existing projects in the data directory are automatically available after a restart and do not need archive import. ZIP imports are limited to 2 GiB of uncompressed contents and 10,000 entries.

The native `.blend` output can be opened in ordinary Blender. Textures supported by Blender's pack operation are packed before saving. Arbitrary external caches generated by advanced scripts may need additional packaging.

## Trusted Python mode

Arbitrary Python execution is disabled by default. To enable it for trusted local agents:

```powershell
.\.venv\Scripts\python.exe -m forge3d stop
.\.venv\Scripts\python.exe -m forge3d start --allow-python
```

`execute_blender_python` opens a copy of the current `.blend` and executes code with `bpy`. This provides access to rigging, UVs, Geometry Nodes, simulations, compositing, and custom exporters. It is access to Blender's API, not a finished collection of specialized tools; some UI-dependent operators cannot run headlessly.

This mode is **not a sandbox** and runs with the user's operating-system privileges. After Python edits, the JSON scene description is no longer assumed accurate: continue in Python mode or submit a new full declarative scene. Native projects and revision history are preserved in both modes.

Not all procedural materials and Blender effects can be represented in glTF. Use the Blender render as the final visual reference.

## Storage and reliability

```text
data/
  token
  service.log
  projects/<project_id>/
    project.json
    assets/<asset_id>/...
    revisions/<revision_id>/
      scene.json
      scene.blend
      preview.glb
      manifest.json
      render_00001.png
  jobs/<job_id>/
  exports/<archive_id>.zip
```

`scene.json` is present for declarative revisions. Render images are included in a revision when rendering was part of its build. Separate render jobs keep their output in the jobs directory.

A new current revision is published only after Blender succeeds and the required files exist. Failure or cancellation preserves the previous successful revision. Following an unexpected service stop, unfinished jobs become `interrupted` on restart; they are not automatically replayed. Atomic metadata replacement includes retries for short Windows file locks. This is not a guarantee against disk or power failure.

There is one Blender worker, a queue limit of 32 jobs, and a default job timeout of 600 seconds. Change the timeout with `serve --timeout N`. History and job outputs are not automatically pruned. CPU rendering uses two threads by default; memory and VRAM are not hard-limited.

## Local API and configuration

The service binds to loopback at `http://127.0.0.1:8765`. All modifying requests require `Authorization: Bearer <contents of data/token>`. Host and Origin checks reject foreign origins. This is a service for one trusted local user, not an internet-facing server.

Set `FORGE3D_DATA` for a different data directory and `FORGE3D_PORT` for a different port. The CLI also accepts `--port` before the subcommand. Do not publish local tokens, generated MCP configuration, private projects, or logs.

See the [API reference](API.md), [validation report](VALIDATION.md), and [roadmap](../PLAN.md) for details and current limits.
