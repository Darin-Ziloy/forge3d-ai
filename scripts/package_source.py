"""Build a source release including only the viewer dependencies actually used."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent.parent
files = set()
for directory in ["forge3d", "scripts", "tests", "docs", "examples"]:
    for file in (root / directory).rglob("*"):
        if file.is_file() and "__pycache__" not in file.parts and "vendor" not in file.parts:
            files.add(file)
for name in ["README.md", "PLAN.md", "CONTRIBUTING.md", "LICENSE", "THIRD_PARTY.md", "pyproject.toml", "package.json", "package-lock.json", "requirements-lock-windows-py314.txt", "Setup.ps1", "Start-Forge3D.cmd", "Start-Demo.cmd", "Stop-Forge3D.cmd", ".gitignore", ".gitattributes"]:
    files.add(root / name)
for name in ["build/three.module.js", "build/three.core.js", "examples/jsm/controls/OrbitControls.js", "examples/jsm/loaders/GLTFLoader.js", "examples/jsm/utils/BufferGeometryUtils.js", "examples/jsm/environments/RoomEnvironment.js", "LICENSE"]:
    files.add(root / "forge3d" / "web" / "vendor" / name)
destination = root / "output" / "Forge3D-AI-0.2.0-source.zip"
destination.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(destination,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for file in sorted(files):
        archive.write(file,"Forge3D-AI/"+file.relative_to(root).as_posix())
with zipfile.ZipFile(destination) as archive:
    assert archive.testzip() is None
    assert not any("data/token" in name or "/.venv/" in name for name in archive.namelist())
print(f"{destination} ({destination.stat().st_size:,} bytes; {len(files)} files)")
