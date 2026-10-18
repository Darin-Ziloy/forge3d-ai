# Contributing

Use English for source comments, UI strings, documentation, examples, issues, and pull requests. Keep changes focused and document user-visible behavior and limitations.

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . pytest==8.4.2
npm.cmd ci --ignore-scripts --no-audit --no-fund
npm.cmd run vendor
```

Blender is required for real pipeline tests and interactive use, but not for the default unit/MCP tests. Set `BLENDER_PATH` when automatic discovery does not find your installation.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check forge3d/web/app.js
```

Run real Blender tests separately:

```powershell
$env:FORGE3D_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest -q
```

The integration test generates its own fixtures and checks modeling, animation, rendering, import formats, revisions, archives, cancellation, and restart persistence. Do not claim a platform or format variant is verified without running it.

For MCP smoke testing against a running local workspace:

```powershell
.\.venv\Scripts\python.exe scripts/check_mcp.py
.\.venv\Scripts\python.exe scripts/check_mcp.py --job COMPLETED_RENDER_JOB_ID
```

## Repository hygiene

Never commit `data/`, tokens, generated `mcp-config.json`, local credentials, virtual environments, private models, or test outputs. Dependencies are restored from `pyproject.toml` and `package-lock.json`. The Python lock snapshot is specific to the original Windows/Python 3.14 environment, not a universal cross-platform lockfile.

To prepare a source bundle with the necessary local Three.js modules:

```powershell
.\.venv\Scripts\python.exe scripts/package_source.py
```

Contributions are distributed under GPL-3.0-or-later, consistent with the repository license. Preserve third-party attribution and license files.
