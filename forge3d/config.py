import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def data_dir():
    return Path(os.environ.get("FORGE3D_DATA", ROOT / "data")).resolve()

def find_blender():
    explicit = os.environ.get("BLENDER_PATH")
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"BLENDER_PATH does not exist: {path}")
        return str(path.resolve())
    found = shutil.which("blender")
    if found:
        return found
    candidates = list((ROOT / "runtime").glob("**/blender.exe"))
    for base in [os.environ.get("ProgramFiles", "C:/Program Files"), os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")]:
        candidates += list(Path(base).glob("Blender Foundation/Blender */blender.exe"))
        candidates += list(Path(base).glob("Steam/steamapps/common/Blender/blender.exe"))
    if candidates:
        return str(sorted(candidates, reverse=True)[0])
    raise FileNotFoundError("Blender not found. Set BLENDER_PATH to blender.exe (portable or installed).")

def hidden_flags():
    import subprocess
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
