# JSON API 0.2

Base URL: `http://127.0.0.1:8765`. All POST requests require JSON and `Authorization: Bearer <contents of data/token>`. GET requests do not require a token but are restricted by local Host/Origin checks.

Errors use `{"error":"...","type":"..."}`. Status codes: 400 invalid parameters, 403 denied access, 404 missing resource, and 409 revision or queue conflict.

| Method and path | Request / response |
|---|---|
| GET `/api/health` | Service version, Blender path, Python-mode flag, active job |
| GET `/api/schema` | Build and patch JSON schemas |
| GET `/api/projects` | Saved projects |
| POST `/api/projects` | `{"name":"Project"}` → project ID |
| GET `/api/projects/{id}` | Current revision, history, scene, and manifest |
| POST `/api/projects/{id}/assets` | `{"source":"C:/Models/model.glb"}` → asset reference |
| POST `/api/projects/{id}/build` | `{"expected_revision":null,"scene":{...},"render":{"enabled":false}}` |
| POST `/api/projects/{id}/patch` | `{"expected_revision":"...","upsert_objects":[],"delete_objects":[],"upsert_materials":[]}` |
| POST `/api/projects/{id}/render` | `{"expected_revision":"...","render":{"frames":[1,24],"width":640,"height":480,"samples":16}}` |
| POST `/api/projects/{id}/restore` | `{"expected_revision":"...","revision":"older_revision"}` |
| POST `/api/projects/{id}/python` | `{"expected_revision":"...","code":"..."}`; opt-in |
| POST `/api/projects/{id}/archive` | `{}` → ZIP path and URL |
| POST `/api/open-archive` | `{"source":"C:/Archives/project.zip"}` → new independent project |
| GET `/api/jobs` | Latest 100 jobs |
| GET `/api/jobs/{id}` | Status, progress, last 6,000 log bytes, and successful output manifest |
| POST `/api/jobs/{id}/cancel` | `{}` |
| POST `/api/shutdown` | `{}` → service shutdown |

Build, patch, restore, Python, and render return a job `id` immediately. Poll until `status` is `succeeded`, `failed`, `cancelled`, or `interrupted`. `expected_revision=null` is only valid for a project's first build. An unfinished job blocks additional jobs for the same project. The global queue holds up to 32 jobs. Default timeout is 600 seconds; use `serve --timeout N` to change it.

## Artifacts

- `/artifacts/projects/{project}/{revision}/scene.blend`
- `/artifacts/projects/{project}/{revision}/preview.glb`
- `/artifacts/projects/{project}/{revision}/scene.json`
- `/artifacts/jobs/{job}/render_00001.png`
- `/artifacts/jobs/{job}/preview.glb` after `progress.preview=true`
- The ZIP URL returned by the archive endpoint.

A declarative build replaces the entire scene. Transform vectors are `[x,y,z]`, distances are meters, rotations are degrees, and parent/material references use IDs. Schema limits catch invalid inputs but do not impose hard Blender memory limits.

A render failure during a combined build-and-render job prevents publication of that whole revision. To save geometry independently of rendering, submit build and render as separate jobs.

## Python client example

```python
from forge3d.client import Client

c = Client()
c.ensure()
p = c.request('/api/projects', {'name': 'Cube'})
j = c.request(f"/api/projects/{p['id']}/build", {
    'expected_revision': None,
    'scene': {'objects': [{'id': 'body', 'type': 'cube'}]}
})
result = c.wait(j['id'])
assert result['status'] == 'succeeded', result
```

## Textured assets

The existing assets endpoint also imports PNG/JPEG files. The build schema adds material texture slots, per-object `uv`, and scene `bakes`, `asset_checks`, and `export_fbx`. See [TEXTURES.md](TEXTURES.md) for complete examples.

New public revision/job outputs: `asset_report.json`, `asset_bundle.zip`, optional `scene.fbx`, and manifest-listed `Textures/*.png` / `UV/*.svg`. Arbitrary nested files remain private. The manifest embeds the asset report and texture/UV output paths.
