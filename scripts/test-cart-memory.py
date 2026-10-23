#!/usr/bin/env python3
"""Local regression check for cart POSTs retaining large analytics buffers."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DLL = ROOT / "GrubifyApi" / "bin" / "Release" / "net9.0" / "GrubifyApi.dll"


def rss_kib(pid):
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    raise RuntimeError("VmRSS unavailable")


def request(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urlopen(req, timeout=3) as response:
        return response.status, json.load(response)


def main():
    if not DLL.exists():
        raise RuntimeError("Build first: dotnet build GrubifyApi/GrubifyApi.csproj -c Release")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, ASPNETCORE_URLS=base, ASPNETCORE_ENVIRONMENT="Production")
    proc = subprocess.Popen(["dotnet", str(DLL)], cwd=DLL.parent, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if proc.poll() is not None:
                raise RuntimeError(f"API exited with status {proc.returncode}")
            try:
                status, _ = request(base + "/api/restaurants")
                if status == 200:
                    break
            except URLError:
                time.sleep(0.1)
        else:
            raise RuntimeError("API did not become ready")
        before = rss_kib(proc.pid)
        for count in range(1, 13):
            status, cart = request(base + "/api/cart/memory-regression/items",
                                   {"foodItemId": 1, "quantity": 1})
            assert status == 200 and cart["items"][0]["quantity"] == count
        time.sleep(0.2)
        growth = rss_kib(proc.pid) - before
        assert growth < 80 * 1024, f"Cart retained too much memory: {growth / 1024:.1f} MiB"
        print(f"PASS: 12 cart POSTs returned 200, quantity 12, RSS growth {growth / 1024:.1f} MiB")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, RuntimeError, URLError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
