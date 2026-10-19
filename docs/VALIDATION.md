# Validation report

## Baseline validation — October 17, 2026

The complete local suite passed: **25 tests in 36.63 seconds**, including real Blender operations and a real MCP stdio connection. JUnit reports are generated under the ignored `test-results/` directory.

Verified environment: Windows NT 10.0.19044 (Windows 10), Python 3.14.4, Node.js 24.15.0, Blender 5.2.2 LTS from Steam, MCP SDK 2.3.0, and Three.js 0.180.0. Windows 11 was not separately tested.

Coverage:

- Rejection of parent cycles, missing materials, NaN, invalid mesh indices, duplicate IDs, invalid frames, and unknown fields.
- Copying glTF dependencies; rejecting external URIs and paths outside the asset directory; ZIP traversal protection.
- Authentication of mutations, Host/Origin checks, and exclusion of private files from static/artifact routes.
- Python disabled by default, stale revision rejection, and exclusive ownership of a data directory.
- Real MCP stdio discovery, project creation/reading, and schema errors.
- Real Blender scene creation, keyframes, GLB animation/mesh contents, PNG frames 1 and 25, and native `.blend` output.
- Scene changes, revision restore, and preservation of the successful revision after a deliberate script failure.
- Real GLB, glTF, OBJ, STL, and FBX imports using Blender-generated fixtures; all five meshes present in the output scene.
- Project ZIP save/open and rebuilding from the copied assets in the reopened project.
- Cancellation, service restart, and persistence of successful project revisions.

`scripts/check_mcp.py --job ID` separately verifies that a completed PNG is returned as native MCP image content. This smoke check passed for the demo.

## Demo and visual inspection

**Orbital / inspection drone** contains 18 scene objects, six materials, a camera, three lights, and 121 frames at 24 FPS. A build with a 960 x 720 Cycles CPU render at 16 samples took **27.78 seconds** on the original test machine. This is one observation, not a general benchmark.

The browser viewer was checked for GLB display, automatic revision updates, play/pause, rewind, orbit, scroll-wheel zoom, framing, render preview, and download links. The screenshot in `docs/images/forge3d-workspace.png` shows the English interface.

The viewer uses studio lighting and is not expected to match the final PNG pixel-for-pixel. `preview_hidden` hides an object only in the viewer; exported geometry and Blender renders retain it.

## English-language update — October 18, 2026

Application-owned UI strings, documentation, example text, and test labels were translated to English. Unicode persistence coverage remains in place using an escaped checkmark rather than language-specific text. Generated local projects, logs, dependencies, and installation-specific configuration are excluded from the published repository.

After translation, the default suite passed: **24 passed, 1 skipped in 7.48 seconds**. The skipped test is the opt-in real-Blender integration test. `node --check forge3d/web/app.js` also passed, and the running viewer was inspected in English.

Run the commands in [CONTRIBUTING.md](../CONTRIBUTING.md) to reproduce unit/MCP checks and the optional real-Blender suite.

## Texture and UV update — October 19, 2026

The full suite passed with real Blender enabled: **29 passed in 43.44 seconds**. After fixing the viewer's embedded-image CSP policy, the service/MCP regression suite passed again: **6 passed in 6.57 seconds**. JavaScript syntax validation also passed.

Additional coverage:

- Explicit per-corner UV validation, missing-image and path-escape rejection.
- Textured GLB output with embedded images and UV attributes; textured FBX and GLB reimport.
- Packed project restore and rebuild after removing the original image and original project's asset copy.
- Atomic rejection of collapsed textured UVs and triangle-budget violations.
- Albedo, normal, roughness, and metallic texture slots, including glTF metallic/roughness packing.
- Smart UV projection and real Cycles selected-to-active albedo/normal baking, removing high sources before export.
- Manifest-listed PNG/SVG artifact access, private-file rejection, and native MCP texture-image output.

The `casual-lowpoly-props` atlas generator and `scripts/create_textured_example.py` produced the live **Forge3D 0.2 / textured package** demo: 12 triangles, one mesh, one material, one 1024 x 1024 atlas, and a UV_Main layer with no collapsed faces. The browser was visually inspected for the textured model, atlas, UV layout, and FBX/ZIP/report download controls. The saved render also shows the printed artwork.

The browser previously blocked GLTFLoader's `fetch(blob:...)` while loading embedded images. Allowing local blob fetches in `connect-src` fixes that issue while retaining the existing local-origin policy. Existing embedded-texture GLBs can benefit after a page refresh; untextured geometry still needs artwork and material assignment.

![Textured package and asset inspector](images/forge3d-textures.png)

To repeat the native image check for a saved textured project:

```powershell
.\.venv\Scripts\python.exe scripts\check_mcp.py --texture-project PROJECT_ID
```

## Remaining unverified areas

Windows 11, other Blender/GPU combinations, large production scenes, all third-party FBX/MTL variants, specialized rigging/simulation/Geometry Nodes APIs, and remote MCP clients remain unverified. Generated fixtures cover the main import path, not every format feature. There is no hard memory limit or Windows Job Object controlling the complete process tree. These items are tracked in the roadmap.
