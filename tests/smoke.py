"""Starts a built app, checks it serves the setup page and answers its API, then stops it with the
Close setup call. Used in CI on each platform; no TV needed.

    python tests/smoke.py "<path to the app's program>"
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

PORT = 8799


def get(path, key=None, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST")
    if key:
        req.add_header("X-Setup-Key", key)
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode()


def main(program):
    env = dict(os.environ, COUCHTV_SETUP_PORT=str(PORT), COUCHTV_SETUP_NO_BROWSER="1",
               COUCHTV_SETUP_HOME=tempfile.mkdtemp())
    proc = subprocess.Popen([program], env=env)
    try:
        page = None
        for _ in range(60):   # a frozen app can take a while to unpack on first start
            try:
                page = get("/")
                break
            except OSError:
                time.sleep(1)
        assert page, "the app never served its page"
        key = re.search(r'name="setup-key" content="([^"]+)"', page).group(1)
        os_name = re.search(r'name="setup-os" content="([^"]+)"', page).group(1)
        assert "__SETUP" not in page, "the page placeholders were not filled in"
        for f in ("style.css", "app.js"):
            assert len(get("/" + f)) > 1000, f + " is missing"
        assert json.loads(get("/api/ping", key))["ok"]
        assert json.loads(get("/api/quit", key, {}))["ok"]
        code = proc.wait(timeout=20)
        assert code == 0, f"the app stopped with code {code}"
        print(f"smoke ok: page, files and API answer ({os_name}), Close setup stops it")
    finally:
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    main(sys.argv[1])
