import json
import zipfile
import pytest
from pydantic import ValidationError
from forge3d.schema import SceneSpec
from forge3d.storage import within, import_asset, open_archive, atomic_json

@pytest.mark.parametrize("scene", [
    {"objects":[{"id":"a","parent":"b"},{"id":"b","parent":"a"}]},
    {"objects":[{"id":"a","material":"missing"}]},
    {"objects":[{"id":"a","location":[float("nan"),0,0]}]},
    {"objects":[{"id":"a"},{"id":"a"}]},
    {"objects":[{"id":"a","type":"mesh","vertices":[[0,0,0]],"faces":[[0,1,2]]}]},
    {"objects":[{"id":"a","type":"import"}]},
    {"objects":[{"id":"a","keyframes":[{"frame":121}]}]},
    {"objects":[{"id":"a","modifiers":[{"type":"subdivision","levels":9}]}]},
    {"unknown_setting":True},
])
def test_invalid_scenes_rejected(scene):
    with pytest.raises(ValidationError):
        SceneSpec.model_validate(scene)

def test_dependent_assets_are_copied(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "mesh.bin").write_bytes(b"mesh")
    (source / "model.gltf").write_text(json.dumps({"asset":{"version":"2.0"},"buffers":[{"uri":"mesh.bin"}]}))
    result = import_asset(tmp_path / "project", str(source / "model.gltf"))
    copied = tmp_path / "project" / "assets" / result["asset"]
    assert copied.is_file()
    assert copied.with_name("mesh.bin").read_bytes() == b"mesh"
    assert result["files"] == 2

@pytest.mark.parametrize("path", ["../secret", "C:/secret", "/outside/secret", "..\\secret"])
def test_path_escape_rejected(tmp_path, path):
    with pytest.raises(ValueError):
        within(tmp_path, path)

@pytest.mark.parametrize("uri", ["https://example.com/a.bin", "../secret.bin", "C:/secret.bin"])
def test_external_gltf_resources_rejected(tmp_path, uri):
    file = tmp_path / "bad.gltf"
    file.write_text(json.dumps({"buffers":[{"uri":uri}]}))
    with pytest.raises(ValueError):
        import_asset(tmp_path / "project", str(file))

def test_archive_rejects_traversal(tmp_path):
    file = tmp_path / "bad.zip"
    with zipfile.ZipFile(file,"w") as z:
        z.writestr("project.json",json.dumps({"name":"Bad","revision":None,"history":[]}))
        z.writestr("assets/../../escaped.txt","bad")
    with pytest.raises(ValueError):
        open_archive(tmp_path / "data", str(file))
    assert not (tmp_path / "data" / "escaped.txt").exists()

def test_atomic_json_unicode(tmp_path):
    file = tmp_path / "Project" / "scene.json"
    atomic_json(file, {"name":"Model \u2713"})
    assert json.loads(file.read_text(encoding="utf-8"))["name"] == "Model \u2713"
