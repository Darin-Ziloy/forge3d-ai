# Third-party components

Forge3D is an independent GPL-3.0-or-later project. It is not affiliated with the Blender Foundation.

| Component | Role | License / origin |
|---|---|---|
| Blender | Separate installed background process | [Blender license](https://www.blender.org/about/license/); binaries are not included |
| Three.js 0.180.0 | Local WebGL viewer, GLTFLoader, OrbitControls, RoomEnvironment | MIT, [repository](https://github.com/mrdoob/three); LICENSE copied to web/vendor/LICENSE |
| MCP Python SDK 2.3.0 | Protocol adapter | MIT, [repository](https://github.com/modelcontextprotocol/python-sdk) |
| Pydantic 2.14.1 | Validation and JSON Schema | MIT, [repository](https://github.com/pydantic/pydantic) |
| Python / setuptools / pytest | Runtime, packaging, tests | Their respective upstream licenses |

The Blender worker and all original project code are distributed under GPL-3.0-or-later. The included LICENSE is the standard GNU GPL v3 text from the installed Blender SPDX license collection. Dependency license texts remain in their distributions. Consult package metadata for transitive dependency licenses. No code was copied from the researched MCP for Blender addon; it was evaluated as an alternative. No downloaded third-party model or texture is used in the demo; the scene is procedurally defined in scripts/create_example.py.

Redistributing a package that includes Blender requires retaining the corresponding licensing/source obligations. This repository does not bundle Blender. The application's license does not automatically impose the same license on the artwork created with it; see [Blender's explanation](https://www.blender.org/about/license/).
