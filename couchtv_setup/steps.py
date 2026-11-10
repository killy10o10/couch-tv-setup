"""The setup steps. Each one looks first and only changes what is not already done, so running a
step twice is safe, and a TV that is already set up is left as it is."""
import json
import os
import time
import urllib.error
import urllib.request

from . import paths
from .tv import TvError

PKG = "dev.couchtv.ontv"
WATCHER = f"{PKG}/{PKG}.WatchService"
RELEASES = "https://api.github.com/repos/Seagey/couch-tv/releases/latest"
APK_NAME = "couch-tv-ontv.apk"

MODELS = {
    "AFTKM": "Fire TV Stick 4K (2nd gen)",
    "AFTKA": "Fire TV Stick 4K Max",
    "AFTKRT": "Fire TV Stick 4K Max (2nd gen)",
    "AFTMM": "Fire TV Stick 4K",
    "AFTSSS": "Fire TV Stick (3rd gen)",
    "AFTSS": "Fire TV Stick Lite",
    "AFTT": "Fire TV Stick (2nd gen)",
    "AFTR": "Fire TV Cube (2nd gen)",
    "AFTGAZL": "Fire TV Cube (3rd gen)",
}

# Ads, tracking and nagging only. Each is switched off (pm disable-user), never deleted, and the
# undo switches it back on. Tested on a Fire TV Stick 4K (2nd gen), Fire OS 8.1.8.5. Never Amazon's
# home (com.amazon.tv.launcher): couch-tv relies on it, and the stick can lose its home without it.
ADS = [
    ("com.amazon.tv.acr", "What's on screen recognition (for ads)"),
    ("com.amazon.hybridadidservice", "Advertising ID"),
    ("com.amazon.sneakpeek", "Sneak peek autoplay trailers"),
    ("com.amazon.media.recommendations", "Sponsored recommendations"),
    ("com.amazon.tv.ftvambient", "Ambient screen adverts"),
    ("com.amazon.device.telemetry.emitter", "Usage telemetry"),
    ("com.amazon.dp.logger", "Usage logging"),
    ("com.amazon.logan", "Diagnostic logs"),
    ("com.amazon.wirelessmetrics.service", "Wi-Fi metrics"),
    ("com.amazon.tv.earlyaccess", "Early access promos"),
    ("com.amazon.tv.releasenotes", "Release notes pop-ups"),
    ("com.amazon.storm.lightning.tutorial", "Tutorial videos"),
    ("com.amazon.tmm.tutorial", "Tutorial pop-ups"),
]


# ---- 1. what is this TV ----

def device(tv):
    model = tv.prop("ro.product.model")
    maker = tv.prop("ro.product.manufacturer")
    os_name = tv.prop("ro.build.version.name")
    sdk = int(tv.prop("ro.build.version.sdk") or 0)
    fire = maker.lower() == "amazon" or "Fire OS" in os_name
    return {
        "model": model,
        "name": MODELS.get(model) or (f"Fire TV ({model})" if fire else f"{maker} {model}".strip()),
        "os": os_name or f"Android (SDK {sdk})",
        "sdk": sdk,
        "fire": fire,
        "supported": fire and sdk >= 28,
        "app": app_state(tv),
    }


def app_state(tv):
    out = tv.shell(f"dumpsys package {PKG}")
    if f"Package [{PKG}]" not in out:
        return {"installed": False}
    version = next((l.split("=", 1)[1].strip() for l in out.splitlines() if "versionName=" in l), None)
    enabled = out.split("enabledComponents:", 1)[1].split("\n\n", 1)[0] if "enabledComponents:" in out else ""
    return {
        "installed": True,
        "version": version,
        "grant": "WRITE_SECURE_SETTINGS: granted=true" in out,
        "home_on": f"{PKG}.HomeAlias" in enabled,
    }


# ---- 2. get the app ----

def _open(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "couch-tv-setup", "Accept": "application/octet-stream, application/json"})
    try:
        import certifi, ssl
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = None
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def download(progress=lambda f, msg=None: None):
    """The newest couch-tv-ontv.apk from Seagey/couch-tv's Releases page, kept in the cache by
    version. COUCHTV_APK=<file> uses that file instead (your own build, say)."""
    own = os.environ.get("COUCHTV_APK")
    if own:
        if not os.path.isfile(own):
            raise TvError(f"COUCHTV_APK points at {own}, which is not there.")
        return {"path": own, "version": "your own build"}
    try:
        with _open(RELEASES) as r:
            rel = json.load(r)
    except (urllib.error.URLError, OSError) as e:
        raise TvError("Could not reach GitHub to download Couch TV. Is this Mac online?", "offline") from e
    asset = next((a for a in rel.get("assets", []) if a.get("name") == APK_NAME), None)
    if not asset:
        raise TvError("The newest Couch TV release has no on-TV app to download.", "no_asset")
    tag = rel.get("tag_name", "latest")
    dest = paths.cache() / f"couch-tv-ontv-{tag}.apk"
    if dest.is_file() and dest.stat().st_size == asset.get("size"):
        return {"path": str(dest), "version": tag}
    part = dest.with_suffix(".part")
    with _open(asset["browser_download_url"], timeout=60) as r, open(part, "wb") as f:
        total, got = int(r.headers.get("Content-Length") or asset.get("size") or 0), 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total:
                progress(got / total, f"Downloading Couch TV {tag}")
    if asset.get("size") and part.stat().st_size != asset["size"]:
        part.unlink()
        raise TvError("The download was cut short. Try again.", "short")
    part.replace(dest)
    return {"path": str(dest), "version": tag}


def install(tv, apk, replace=False, progress=lambda f, msg=None: None):
    if replace:
        progress(0, "Removing the old Couch TV app")
        tv.shell(f"pm uninstall {PKG}")
    tv.install(apk, lambda f: progress(f, "Copying Couch TV to the TV" if f < 1 else "Installing it on the TV"))
    return app_state(tv)


# ---- 3. make it the home screen ----

def make_home(tv, progress=lambda f, msg=None: None):
    """The two grants, "Use as home screen" on, and the Home watcher on and running. Only what is
    missing is changed. Returns what was done and whether the watcher is running."""
    done = []
    state = app_state(tv)
    if not state.get("installed"):
        raise TvError("Couch TV is not on this TV yet.", "not_installed")
    progress(0.1, "Letting Couch TV take back the Home button")
    if not state["grant"]:
        tv.shell(f"pm grant {PKG} android.permission.WRITE_SECURE_SETTINGS")
        done.append("grant")
    if "allow" not in tv.shell(f"appops get {PKG} SYSTEM_ALERT_WINDOW"):
        tv.shell(f"appops set {PKG} SYSTEM_ALERT_WINDOW allow")
        done.append("overlay")
    if not state["home_on"]:
        tv.shell(f"pm enable {PKG}/.HomeAlias")
        done.append("home")
    if done:
        # A fresh start makes the app switch its watcher on (it does that when it starts).
        progress(0.4, "Starting Couch TV")
        tv.shell(f"am force-stop {PKG}; am start -n {PKG}/.SetupActivity")
        time.sleep(4)
    progress(0.6, "Checking the Home watcher")
    if not _watcher_listed(tv):
        cur = tv.shell("settings get secure enabled_accessibility_services").strip()
        new = WATCHER if cur in ("", "null") else f"{cur}:{WATCHER}"
        tv.shell(f"settings put secure enabled_accessibility_services '{new}'; settings put secure accessibility_enabled 1")
        done.append("watcher")
    bound = False
    for _ in range(8):
        if watcher_running(tv):
            bound = True
            break
        time.sleep(1)
    progress(1.0, "Done")
    return {"changed": done, "watcher_running": bound, "other_watchers": other_watchers(tv)}


def _watcher_listed(tv):
    return WATCHER in tv.shell("settings get secure enabled_accessibility_services").strip().split(":")


def watcher_running(tv):
    return "Couch TV home watch" in tv.shell("dumpsys accessibility | grep -i 'Bound services'")


def other_watchers(tv):
    """Other launchers that also take the Home button back (they fight with Couch TV)."""
    known = {"com.spocky.projengmenu": "Projectivy", "com.wolf.firelauncher": "Wolf Launcher"}
    cur = tv.shell("settings get secure enabled_accessibility_services")
    return [name for pkg, name in known.items() if pkg in cur]


def restart(tv):
    """Sent once and never retried: the TV goes away mid-command, and a retry after it came back
    would restart it a second time."""
    try:
        tv.dev.shell("reboot", timeout_s=5, read_timeout_s=5)
    except Exception:
        pass
    tv.close()


def go_home(tv):
    """Presses Home: closes Couch TV's pairing screen, which stays up after pairing."""
    tv.shell("input keyevent KEYCODE_HOME")


def press_home_check(tv):
    """Presses Home and says whether Couch TV is what came up. Waits a moment before the first
    look, so the screen from before the press is not counted."""
    tv.shell("input keyevent KEYCODE_HOME")
    time.sleep(2)
    for _ in range(8):
        time.sleep(1)
        front = tv.shell("dumpsys activity activities 2>/dev/null | grep -m1 mResumedActivity")
        if PKG in front:
            return {"ok": True}
    return {"ok": False}


# ---- 4. ads and tracking ----

def _record():
    return paths.data() / "switched-off.json"


def ads_state(tv, serial=None):
    """Each ad or tracking app on this TV: off or on, and "mine" when this setup switched it off
    (only those come back on with Undo)."""
    off = {l.replace("package:", "").strip() for l in tv.shell("pm list packages -d").splitlines()}
    there = {l.replace("package:", "").strip() for l in tv.shell("pm list packages").splitlines()}
    mine = set(_load_record().get(serial, [])) if serial else set()
    return [{"package": p, "what": w, "off": p in off, "mine": p in mine} for p, w in ADS if p in there]


def ads_off(tv, serial):
    rec = _load_record()
    mine = set(rec.get(serial, []))
    for item in ads_state(tv):
        if not item["off"]:
            out = tv.shell(f"pm disable-user --user 0 {item['package']}")
            if "disabled" in out:
                mine.add(item["package"])
    rec[serial] = sorted(mine)
    _record().write_text(json.dumps(rec, indent=1))
    return ads_state(tv, serial)


def ads_undo(tv, serial):
    """Switches back on what this setup switched off on this TV (and nothing else)."""
    rec = _load_record()
    for p in rec.get(serial, []):
        tv.shell(f"pm enable {p}")
    rec.pop(serial, None)
    _record().write_text(json.dumps(rec, indent=1))
    return ads_state(tv, serial)


def _load_record():
    try:
        return json.loads(_record().read_text())
    except Exception:
        return {}


def serial(tv):
    return tv.prop("ro.serialno") or tv.ip
