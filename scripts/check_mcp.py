"""Check real stdio transport and optionally a completed render as image content."""
import argparse
import asyncio
import base64
import sys
from pathlib import Path
from mcp import Client, StdioServerParameters

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job")
    parser.add_argument("--texture-project", help="Inspect the first saved texture through MCP")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    params = StdioServerParameters(command=sys.executable, args=["-m", "forge3d", "mcp"], env={"PYTHONPATH":str(root)})
    async with Client(params) as client:
        listed = await client.list_tools()
        print(f"MCP stdio connected: {len(listed.tools)} tools")
        result = await client.call_tool("list_projects", {})
        assert not result.is_error, result
        print("Saved projects readable")
        if args.job:
            result = await client.call_tool("view_render", {"job_id":args.job,"frame":1})
            assert not result.is_error, result
            images = [item for item in result.content if item.type == "image"]
            assert images and base64.b64decode(images[0].data).startswith(b"\x89PNG")
            print("PNG returned as native MCP image content")
        if args.texture_project:
            result = await client.call_tool("view_texture", {"project_id": args.texture_project})
            assert not result.is_error, result
            images = [item for item in result.content if item.type == "image"]
            assert images and base64.b64decode(images[0].data).startswith(b"\x89PNG")
            print("Texture PNG returned as native MCP image content")

asyncio.run(main())
