"""Real Blender checks. Run with FORGE3D_INTEGRATION=1; no mocked 3D results."""
import json
import os
from pathlib import Path
import struct
import subprocess
import time
import pytest
from forge3d.config import find_blender, hidden_flags
from forge3d.engine import Engine, Conflict
from forge3d.server import archive
from forge3d.storage import open_archive

pytestmark = pytest.mark.skipif(os.environ.get("FORGE3D_INTEGRATION") != "1", reason="Set FORGE3D_INTEGRATION=1 for real Blender tests")

def wait(engine, job, timeout=180):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        result = engine.job(job["id"])
        if result["status"] not in {"queued","running"}:
            return result
        time.sleep(.2)
    raise TimeoutError(engine.job(job["id"]))

def test_full_pipeline_imports_versions_render_archive_cancel(tmp_path):
    engine = Engine(tmp_path / "workspace", allow_python=True, timeout=180)
    try:
        project = engine.create_project("Integration / model")
        pid = project["id"]
        scene = {"frame_end":25,"objects":[{"id":"cube","location":[0,0,1],"keyframes":[{"frame":1,"rotation":[0,0,0]},{"frame":25,"rotation":[0,0,90]}]}]}
        job = wait(engine,engine.build(pid,{"scene":scene,"render":{"enabled":True,"width":128,"height":128,"samples":1,"frames":[1,25]}}))
        assert job["status"] == "succeeded", job
        first = job["id"]
        base = engine.job_dir(first)
        assert (base / "scene.blend").stat().st_size > 1000
        assert (base / "render_00001.png").read_bytes().startswith(b"\x89PNG")
        assert (base / "render_00025.png").is_file()
        glb = (base / "preview.glb").read_bytes()
        length = struct.unpack_from("<I",glb,12)[0]
        metadata = json.loads(glb[20:20+length])
        assert metadata["animations"]
        assert metadata["meshes"]
        job = wait(engine,engine.patch(pid,{"expected_revision":first,"upsert_objects":[{"id":"cube","location":[2,0,1]}]}))
        assert job["status"] == "succeeded",job
        second = job["id"]
        assert engine.project(pid)["scene"]["objects"][0]["location"] == [2.0,0.0,1.0]
        with pytest.raises(Conflict):
            engine.patch(pid,{"expected_revision":first})
        # A script failure must not publish a partially modified scene.
        failed = wait(engine,engine.python(pid,second,"raise RuntimeError('intentional test failure')",{}))
        assert failed["status"] == "failed"
        assert engine.project(pid)["revision"] == second
        restored = wait(engine,engine.restore(pid,first,second))
        assert restored["status"] == "succeeded",restored
        assert engine.project(pid)["scene"]["objects"][0]["location"] == [0.0,0.0,1.0]
        # Export a tiny real model in all supported input formats.
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        script = fixtures / "export.py"
        script.write_text("import bpy\nfrom pathlib import Path\np="+repr(str(fixtures))+"\nbpy.ops.wm.read_factory_settings(use_empty=True)\nbpy.ops.mesh.primitive_cube_add()\nbpy.ops.export_scene.gltf(filepath=p+'/cube.glb',export_format='GLB')\nbpy.ops.export_scene.gltf(filepath=p+'/cube.gltf',export_format='GLTF_SEPARATE')\nbpy.ops.wm.obj_export(filepath=p+'/cube.obj')\nbpy.ops.wm.stl_export(filepath=p+'/cube.stl')\nbpy.ops.export_scene.fbx(filepath=p+'/cube.fbx')\n")
        result = subprocess.run([find_blender(),"-b","--factory-startup","--python-exit-code","1","--python",str(script)],capture_output=True,timeout=120,creationflags=hidden_flags())
        assert result.returncode == 0,result.stdout.decode(errors="replace")
        imported_objects = []
        for index, ext in enumerate(["glb","gltf","obj","stl","fbx"]):
            asset = engine.assets(pid,str(fixtures / ("cube."+ext)))
            imported_objects.append({"id":"import_"+ext,"type":"import","asset":asset["asset"],"location":[index*3,0,0]})
        imported = wait(engine,engine.build(pid,{"expected_revision":restored["id"],"scene":{"objects":imported_objects}}))
        assert imported["status"] == "succeeded",imported
        assert sum(o["type"]=="MESH" for o in imported["manifest"]["objects"]) == 5
        saved = archive(engine,pid)
        reopened = open_archive(engine.data,saved["path"])
        assert reopened["id"] != pid
        assert reopened["history"] == engine.project(pid)["history"]
        assert len(engine.project(reopened["id"])["scene"]["objects"]) == 5
        # Rebuild the imported project using its own copies of the assets.
        rebuild = wait(engine,engine.build(reopened["id"],{"expected_revision":reopened["revision"],"scene":engine.project(reopened["id"])["scene"]}))
        assert rebuild["status"] == "succeeded",rebuild
        revision = engine.project(pid)["revision"]
        sleeping = engine.python(pid,revision,"import time; time.sleep(60)",{})
        deadline = time.monotonic()+10
        while engine.job(sleeping["id"])["status"] == "queued" and time.monotonic()<deadline:
            time.sleep(.1)
        engine.cancel(sleeping["id"])
        assert engine.job(sleeping["id"])["status"] == "cancelled"
        assert engine.project(pid)["revision"] == revision
        # Durable metadata survives process/service restart.
        engine.close()
        engine = Engine(tmp_path / "workspace")
        assert engine.project(pid)["revision"] == revision
        assert engine.project(reopened["id"])["revision"] == rebuild["id"]
    finally:
        engine.close()
