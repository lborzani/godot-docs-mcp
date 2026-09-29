"""Smoke test: talks to server.py over stdio like an MCP client. Run: python3 test_server.py"""
import json
import subprocess
import sys
from pathlib import Path

reqs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_docs", "arguments": {"query": "move_and_slide"}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_class", "arguments": {"name": "Node2D", "member": "move_local_x"}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "read_doc", "arguments": {"path": "nope.rst"}}},
    {"jsonrpc": "2.0", "id": 6, "method": "bogus"},
]
out = subprocess.run([sys.executable, str(Path(__file__).with_name("server.py"))], text=True, capture_output=True,
                     input="\n".join(json.dumps(r) for r in reqs) + "\n", check=True).stdout
r = {m["id"]: m for m in map(json.loads, out.splitlines())}
assert r[1]["result"]["serverInfo"]["name"] == "godot-docs"
assert {t["name"] for t in r[2]["result"]["tools"]} == {"search_docs", "read_doc", "get_class"}
assert "characterbody" in r[3]["result"]["content"][0]["text"].lower()
text4 = r[4]["result"]["content"][0]["text"]
assert "move_local_x" in text4 and "delta" in text4 and ":ref:" not in text4
assert "not found" in r[5]["result"]["content"][0]["text"]
assert r[6]["error"]["code"] == -32601
print("ok")

# HTTP transport
import os, time, urllib.request, urllib.error
env = {**os.environ, "MCP_PORT": "8799", "MCP_HOST": "127.0.0.1", "MCP_TOKEN": "t0k"}
srv = subprocess.Popen([sys.executable, str(Path(__file__).with_name("server.py")), "--http"], env=env, stderr=subprocess.DEVNULL)
try:
    def post(body, headers):
        req = urllib.request.Request("http://127.0.0.1:8799/mcp", json.dumps(body).encode(),
                                     {"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as e:
            return e.code, b""
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:8799/health"); break
        except OSError:
            time.sleep(0.1)
    auth = {"Authorization": "Bearer t0k"}
    assert post(reqs[0], {})[0] == 401
    assert post(reqs[0], {**auth, "Origin": "http://evil.example"})[0] == 403
    assert post(reqs[1], auth)[0] == 202
    code, body = post(reqs[4], auth)
    assert code == 200 and "move_local_x" in json.loads(body)["result"]["content"][0]["text"]
finally:
    srv.terminate()
print("http ok")
