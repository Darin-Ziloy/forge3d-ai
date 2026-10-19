import asyncio
import json
import os
import sys
import threading
import urllib.error
import urllib.request
import pytest
from mcp import Client, StdioServerParameters
from forge3d.config import ROOT
from forge3d.engine import Engine, Conflict
from forge3d.server import make_server

@pytest.fixture
def server(tmp_path):
    server = make_server(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join()
    server.engine.close()
    server.server_close()

def send(server, path, body=None, headers=None):
    url = f"http://127.0.0.1:{server.server_address[1]}" + path
    request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers or {})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request) as result:
        return json.load(result)

def test_auth_origin_and_host(server):
    assert send(server,"/api/health")["service"] == "forge3d"
    for headers in [{}, {"Authorization":"Bearer wrong"}, {"Authorization":"Bearer "+server.engine.token,"Origin":"https://attacker.example"}]:
        with pytest.raises(urllib.error.HTTPError) as e:
            send(server,"/api/projects",{"name":"x"},headers)
        assert e.value.code == 403
    with pytest.raises(urllib.error.HTTPError) as e:
        send(server,"/api/health",headers={"Host":"evil.example"})
    assert e.value.code == 403
    result = send(server,"/api/projects",{"name":"My project"},{"Authorization":"Bearer "+server.engine.token})
    assert result["name"] == "My project"

def test_private_files_not_served(server):
    for path in ["/../token", "/artifacts/jobs/foo/request.json", "/%2e%2e/token"]:
        with pytest.raises(urllib.error.HTTPError) as e:
            send(server, path)
        assert e.value.code in {400,404}

def test_python_disabled_and_revision_conflict(server):
    engine = server.engine
    project = engine.create_project("Version check")
    with pytest.raises(PermissionError):
        engine.python(project["id"],None,"print('x')",{})
    with pytest.raises(Conflict):
        engine.build(project["id"],{"scene":{},"expected_revision":"stale"})

def test_single_owner_per_data_dir(server):
    with pytest.raises(Conflict):
        Engine(server.engine.data)

def test_texture_output_whitelist(server):
    from forge3d.storage import atomic_json
    base = server.engine.data / "jobs" / "fixture"
    atomic_json(base / "job.json", {"id":"fixture", "created":0, "status":"succeeded"})
    atomic_json(base / "manifest.json", {"textures":["Textures/000_atlas.png"],"uv_layouts":["UV/0000.svg"]})
    (base / "Textures").mkdir(); (base / "UV").mkdir()
    (base / "Textures" / "000_atlas.png").write_bytes(b"public PNG fixture")
    (base / "Textures" / "secret.png").write_bytes(b"private")
    (base / "UV" / "0000.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    url = f"http://127.0.0.1:{server.server_address[1]}/artifacts/jobs/fixture/"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for path in ["Textures/000_atlas.png","UV/0000.svg"]:
        with opener.open(url+path) as response:
            assert response.status == 200
            assert response.headers['X-Content-Type-Options']=='nosniff'
            assert "connect-src 'self' blob:" in response.headers['Content-Security-Policy']
    for path in ["Textures/secret.png","Textures/../job.json","UV/../../token"]:
        with pytest.raises(urllib.error.HTTPError) as error: opener.open(url+path)
        assert error.value.code == 404

def test_mcp_real_stdio_transport(server):
    async def scenario():
        params = StdioServerParameters(command=sys.executable, args=["-m","forge3d","--port",str(server.server_address[1]),"mcp"], env={"PYTHONPATH":str(ROOT),"FORGE3D_DATA":str(server.engine.data)})
        async with Client(params) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert 'view_texture' in names
            capabilities = await client.call_tool('capabilities', {})
            assert not capabilities.is_error
            assert 'base_color_texture' in str(capabilities) and 'UVSpec' in str(capabilities)
            assert {"build_scene","import_asset","save_project_archive","open_project_archive","view_render"} <= names
            result = await client.call_tool("create_project", {"name":"MCP integration"})
            assert not result.is_error
            result = await client.call_tool("list_projects", {})
            assert not result.is_error
            assert "MCP integration" in str(result)
            result = await client.call_tool("build_scene", {"project_id":"missing","scene":{"objects":[{"id":"a","parent":"a"}]}})
            assert result.is_error
    asyncio.run(scenario())
