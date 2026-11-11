"""A small web server on this Mac only (127.0.0.1) that serves the setup page and runs the steps.

Slow steps (waiting for Allow, downloading, copying the app) run as a job in the background; the
page asks GET /api/job how it is going.
"""
import json
import os
import time
import secrets
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import finder, steps
from .couchtv import CouchTv
from .tv import Tv, TvError

WEB = (Path(sys._MEIPASS) / "couchtv_setup" if getattr(sys, "frozen", False) else Path(__file__).parent) / "web"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png"}


class State:
    def __init__(self):
        self.tv = None
        self.ip = None
        self.couch = None
        self.apk = None
        self.lock = threading.Lock()
        self.job = {"running": False}
        self.httpd = None


S = State()
SEEN = {"last": None, "started": time.time()}
IDLE_S = 180          # the page asks every 20 s; this long without it means the tab is closed
FIRST_S = 600         # time to open the page at all
# Only this page may call the API: other websites open in the browser cannot guess it.
SECRET = secrets.token_urlsafe(16)


def run_job(name, fn):
    with S.lock:
        if S.job.get("running"):
            raise TvError("Still busy with the last step.", "busy")
        S.job = {"name": name, "running": True, "progress": 0, "message": ""}

    def progress(frac, msg=None):
        S.job["progress"] = round(frac, 3)
        if msg:
            S.job["message"] = msg

    def work():
        try:
            S.job["result"] = fn(progress)
        except TvError as e:
            S.job.update(error=str(e), code=e.code)
        except Exception as e:
            traceback.print_exc()
            S.job.update(error=f"Something went wrong: {type(e).__name__}: {e}", code="crash")
        finally:
            S.job["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return {"started": name}


def need_tv():
    if not S.tv:
        raise TvError("Connect to the TV first.", "no_tv")
    return S.tv


# ---- the API ----

def api(method, path, body):
    SEEN["last"] = time.time()
    if path == "/api/ping":
        return {"ok": True}
    if path == "/api/quit":
        # The "Close setup" button. Answers first, then stops the server a moment later.
        if S.job.get("running"):
            raise TvError("Still busy with the last step. Wait for it to finish, then close.", "busy")
        threading.Timer(0.5, S.httpd.shutdown).start()
        return {"ok": True}
    if path == "/api/job":
        return S.job
    if path == "/api/scan":
        return {"tvs": finder.scan(), "networks": [str(n) for n in finder.local_networks()]}
    if path == "/api/connect":
        ip = (body.get("ip") or "").strip()
        if not ip:
            raise TvError("Type the TV's address first.", "no_ip")

        def connect(progress):
            progress(0.2, "Waiting for you to press Allow on the TV")
            if S.tv:
                S.tv.close()
            S.tv, S.ip = Tv(ip), ip
            S.couch = CouchTv(ip, os.environ.get("COUCHTV_SETUP_TOKEN"))  # a token only for testing
            progress(0.9, "Looking at the TV")
            return steps.device(S.tv)
        return run_job("connect", connect)
    if path == "/api/device":
        return steps.device(need_tv())
    if path == "/api/install":
        tv = need_tv()
        replace = bool(body.get("replace"))

        def install(progress):
            apk = steps.download(progress)
            S.apk = apk
            state = steps.install(tv, apk["path"], replace=replace, progress=progress)
            return {"apk": apk, "app": state}
        return run_job("install", install)
    if path == "/api/home":
        tv = need_tv()
        return run_job("home", lambda progress: steps.make_home(tv, progress))
    if path == "/api/restart":
        steps.restart(need_tv())
        S.tv = None
        return {"ok": True}
    if path == "/api/check":
        tv = need_tv()
        return run_job("check", lambda progress: steps.press_home_check(tv))
    if path == "/api/pair/start":
        need_tv()
        return S.couch.pair_start()
    if path == "/api/pair":
        need_tv()
        S.couch.pair(body.get("pin", ""))
        steps.go_home(S.tv)
        return {"ok": True}
    if path == "/api/apps":
        need_tv()
        return S.couch.apps()
    if path == "/api/personalise":
        need_tv()
        return S.couch.personalise(body.get("weather"), body.get("country"), body.get("people"),
                                   body.get("order"), body.get("line"))
    if path == "/api/ads":
        tv = need_tv()
        action = body.get("action")
        if action == "off":
            return {"apps": steps.ads_off(tv, steps.serial(tv))}
        if action == "undo":
            return {"apps": steps.ads_undo(tv, steps.serial(tv))}
        return {"apps": steps.ads_state(tv, steps.serial(tv))}
    raise TvError("No such step.", "404")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if os.environ.get("COUCHTV_SETUP_DEBUG"):
            super().log_message(fmt, *args)

    def _send(self, code, data, ctype="application/json"):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _api(self, method):
        if self.headers.get("X-Setup-Key") != SECRET:
            return self._send(403, {"error": "not this page"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            body = {}
        try:
            self._send(200, api(method, self.path.split("?")[0], body))
        except TvError as e:
            self._send(400, {"error": str(e), "code": e.code})
        except Exception as e:
            traceback.print_exc()
            self._send(500, {"error": f"Something went wrong: {type(e).__name__}: {e}"})

    def do_POST(self):
        self._api("POST")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            return self._api("GET")
        name = "index.html" if path in ("", "/") else path.lstrip("/")
        f = (WEB / name).resolve()
        if WEB.resolve() not in f.parents or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        raw = f.read_bytes()
        if name == "index.html":
            raw = raw.replace(b"__SETUP_KEY__", SECRET.encode())
        self._send(200, raw, TYPES.get(f.suffix, "application/octet-stream"))


def main():
    port = int(os.environ.get("COUCHTV_SETUP_PORT") or 0)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    S.httpd = httpd
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"Couch TV Setup is open in your browser: {url}")
    print("Keep this window open until you are done. Close it (or press Ctrl+C) to stop.")
    if not os.environ.get("COUCHTV_SETUP_NO_BROWSER"):
        webbrowser.open(url)

    def stop_when_closed():
        # The Mac app has no window of its own: it stops by itself once the page is closed.
        while True:
            time.sleep(10)
            now = time.time()
            if SEEN["last"] is None and now - SEEN["started"] > FIRST_S or \
                    SEEN["last"] is not None and now - SEEN["last"] > IDLE_S and not S.job.get("running"):
                print("The setup page was closed, so Couch TV Setup has stopped.")
                httpd.shutdown()
                return
    threading.Thread(target=stop_when_closed, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if S.tv:
            S.tv.close()
