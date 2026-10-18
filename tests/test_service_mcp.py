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

def test_mcp_real_stdio_transport(server):
    async def scenario():
        params = StdioServerParameters(command=sys.executable, args=["-m","forge3d","--port",str(server.server_address[1]),"mcp"], env={"PYTHONPATH":str(ROOT),"FORGE3D_DATA":str(server.engine.data)})
        async with Client(params) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {"build_scene","import_asset","save_project_archive","open_project_archive","view_render"} <= names
            result = await client.call_tool("create_project", {"name":"MCP integration"})
            assert not result.is_error
            result = await client.call_tool("list_projects", {})
            assert not result.is_error
            assert "MCP integration" in str(result)
            result = await client.call_tool("build_scene", {"project_id":"missing","scene":{"objects":[{"id":"a","parent":"a"}]}})
            assert result.is_error
    asyncio.run(scenario())
