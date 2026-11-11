"""The on-TV app's own API (port 5400): pairing with the code shown on the TV, then the home's
settings (weather, country, names, dock). The same calls the phone remote makes."""
import json
import sys
import urllib.error
import urllib.request

from .tv import TvError

PORT = 5400


class CouchTv:
    def __init__(self, ip, token=None):
        self.base = f"http://{ip}:{PORT}"
        self.token = token

    def call(self, method, path, body=None, timeout=15):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e).get("error")
            except Exception:
                msg = None
            raise TvError(msg or f"Couch TV said no ({e.code}).", "api_" + str(e.code)) from e
        except (urllib.error.URLError, OSError) as e:
            raise TvError("Couch TV on the TV is not answering yet. Open it once on the TV and try again.", "api_down") from e

    def health(self):
        return self.call("GET", "/api/health")

    def pair_start(self):
        return self.call("POST", "/api/pair/start", {})

    def pair(self, pin):
        r = self.call("POST", "/api/pair", {"pin": pin.strip(), "name": "Couch TV Setup (" + ("Mac" if sys.platform == "darwin" else "Windows" if sys.platform == "win32" else "computer") + ")"})
        self.token = r["token"]
        return self.token

    def apps(self):
        return self.call("GET", "/api/app-order")

    def personalise(self, weather=None, country=None, people=None, order=None, line=None):
        body = {}
        if weather:
            body["weather"] = weather
        if country:
            body["country"] = country
        if people:
            body["people"] = [{"name": n} for n in people if n.strip()]
        if body:
            self.call("POST", "/api/settings", body)
        if order is not None:
            self.call("POST", "/api/app-order", {"order": order, "line": line if line is not None else len(order)})
        return {"ok": True}
