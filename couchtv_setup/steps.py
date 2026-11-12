"""The setup steps. Each one looks first and only changes what is not already done, so running a
step twice is safe, and a TV that is already set up is left as it is."""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

from . import paths
from .tv import TMP, TvError

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
        raise TvError("Could not reach GitHub to download Couch TV. Is this computer online?", "offline") from e
    asset = next((a for a in rel.get("assets", []) if a.get("name") == APK_NAME), None)
    if not asset:
        raise TvError("The newest Couch TV release has no on-TV app to download.", "no_asset")
    want = (asset.get("digest") or "").lower()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", want):
        raise TvError("GitHub did not say what the Couch TV download should look like, so it was not used.", "no_digest")
    want = want.split(":", 1)[1]
    tag = rel.get("tag_name", "latest")
    dest = paths.cache() / f"couch-tv-ontv-{tag}.apk"
    if dest.is_file() and sha256(dest) == want:
        return {"path": str(dest), "version": tag, "sha256": want}
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
    if sha256(part) != want:
        # cut short, changed on the way, or not the file GitHub lists: never install it
        part.unlink()
        raise TvError("The Couch TV download did not match what GitHub lists for it, so it was thrown away. Try again.", "bad_download")
    part.replace(dest)
    return {"path": str(dest), "version": tag, "sha256": want}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def install(tv, apk, replace=False, progress=lambda f, msg=None: None):
    if replace:
        progress(0, "Removing the old Couch TV app")
        tv.shell(f"pm uninstall {PKG}")
    tv.install(apk, lambda f: progress(f, "Copying Couch TV to the TV" if f < 1 else "Installing it on the TV"))
    return app_state(tv)


# ---- 3. make it the home screen ----

def make_home(tv, progress=lambda f, msg=None: None):
    """The two grants, "Use as home screen" on, and the Home watcher on and running. Only what is
    missing is changed. Returns what was done, whether "Use as home screen" is on (if not, the
    person presses it with the remote), and whether the watcher is running."""
    done = []
    state = app_state(tv)
    if not state.get("installed"):
        raise TvError("Couch TV is not on this TV yet.", "not_installed")
    progress(0.1, "Letting Couch TV take back the Home button")
    if not state["grant"]:
        tv.shell(f"pm grant {PKG} android.permission.WRITE_SECURE_SETTINGS")
        done.append("grant")
    # Drawing over other apps, and seeing which app is in front (Fire OS needs both for the Home
    # button: on-tv/README.md in Seagey/couch-tv).
    for op, name in (("SYSTEM_ALERT_WINDOW", "overlay"), ("GET_USAGE_STATS", "usage")):
        if "allow" not in tv.shell(f"appops get {PKG} {op}"):
            tv.shell(f"appops set {PKG} {op} allow")
            done.append(name)
    home_on = state["home_on"]
    if not home_on:
        # Fire OS does not let ADB switch the home alias on ("Shell cannot change component
        # state"), so press the app's own button, as the remote would.
        progress(0.3, "Pressing Use as home screen on the TV")
        home_on = press_use_as_home(tv)
        if home_on:
            done.append("home")
    elif done:
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
    return {"changed": done, "home_on": home_on, "watcher_running": bound, "other_watchers": other_watchers(tv)}


USE_HOME = "Use as home screen"
STOP_HOME = "Stop being the home screen"


def setup_buttons(tv):
    """The buttons on Couch TV's setup screen, in order, as (text, focused)."""
    xml = tv.shell("uiautomator dump /data/local/tmp/couchtv-ui.xml >/dev/null 2>&1; "
                   "cat /data/local/tmp/couchtv-ui.xml; rm -f /data/local/tmp/couchtv-ui.xml", 30)
    out = []
    for node in re.findall(r"<node [^>]*>", xml):
        if 'class="android.widget.Button"' in node and f'package="{PKG}"' in node:
            text = re.search(r'text="([^"]*)"', node)
            out.append((text.group(1) if text else "", 'focused="true"' in node))
    return out


def press_use_as_home(tv):
    """Opens Couch TV's setup screen and presses its "Use as home screen" button with the D-pad.
    It only ever presses select once the highlighted button reads exactly "Use as home screen",
    so it can never land on Forget phones. Returns whether the switch is on afterwards."""
    tv.shell(f"am force-stop {PKG}; am start -n {PKG}/.SetupActivity")
    time.sleep(3)
    for _ in range(8):
        buttons = setup_buttons(tv)
        texts = [t for t, _ in buttons]
        focused = next((i for i, (_, f) in enumerate(buttons) if f), None)
        if STOP_HOME in texts:
            return True
        if USE_HOME not in texts or focused is None:
            return False
        target = texts.index(USE_HOME)
        if focused == target:
            tv.shell("input keyevent KEYCODE_DPAD_CENTER")
            time.sleep(2)
            return app_state(tv).get("home_on", False)
        tv.shell("input keyevent KEYCODE_DPAD_" + ("RIGHT" if target > focused else "LEFT"))
        time.sleep(0.6)
    return False


def _watcher_listed(tv):
    return WATCHER in tv.shell("settings get secure enabled_accessibility_services").strip().split(":")


def watcher_running(tv):
    """Whether Fire OS is running the watcher. The "Bound services" list runs over several lines
    when more than one service is bound (another launcher's, say), so read the whole list."""
    out = tv.shell("dumpsys accessibility")
    bound = out.split("Bound services:", 1)[1].split("Enabled services:", 1)[0] if "Bound services:" in out else ""
    return "Couch TV home watch" in bound


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


def refresh_home(tv):
    """The home only reads its settings and app order again when it comes back on screen (the
    app's onResume), so saving while it is showing changes nothing visible. Opening Couch TV's
    setup screen and pressing Home brings it back, and it shows the new settings at once."""
    tv.shell(f"am start -n {PKG}/.SetupActivity")
    time.sleep(1.5)
    tv.shell("input keyevent KEYCODE_HOME")


def go_home(tv):
    """Presses Home: closes Couch TV's pairing screen, which stays up after pairing."""
    tv.shell("input keyevent KEYCODE_HOME")


def press_home_check(tv):
    """Opens Fire TV's settings, presses Home, and says whether Couch TV is what came up. Home
    pressed while a home screen is already in front changes nothing, so it would prove nothing:
    the settings screen is in front first. Waits a moment before the first look, so the screen
    from before the press is not counted."""
    tv.shell("am start -a android.settings.SETTINGS")
    time.sleep(2.5)
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


# The same list is kept on the TV too, so Undo works from any computer, not only the one that
# switched them off. /data/local/tmp belongs to ADB's shell user and survives restarts.
TV_RECORD = "/data/local/tmp/couchtv-setup/switched-off.txt"


def _tv_record(tv):
    return {l.strip() for l in tv.shell(f"cat {TV_RECORD} 2>/dev/null").splitlines() if l.strip().startswith("com.")}


def _save_tv_record(tv, pkgs):
    if pkgs:
        tv.shell(f"mkdir -p {TV_RECORD.rsplit('/', 1)[0]}; printf '%s\\n' {' '.join(sorted(pkgs))} > {TV_RECORD}")
    else:
        tv.shell(f"rm -f {TV_RECORD}")


def _mine(tv, serial):
    return set(_load_record().get(serial, [])) | _tv_record(tv)


def _save_mine(tv, serial, pkgs):
    rec = _load_record()
    if pkgs:
        rec[serial] = sorted(pkgs)
    else:
        rec.pop(serial, None)
    _record().write_text(json.dumps(rec, indent=1))
    _save_tv_record(tv, pkgs)


def ads_state(tv, serial=None):
    """Each ad or tracking app on this TV: off or on, and "mine" when this setup switched it off
    (only those come back on with Undo)."""
    off = {l.replace("package:", "").strip() for l in tv.shell("pm list packages -d").splitlines()}
    there = {l.replace("package:", "").strip() for l in tv.shell("pm list packages").splitlines()}
    mine = _mine(tv, serial) if serial else set()
    return [{"package": p, "what": w, "off": p in off, "mine": p in mine} for p, w in ADS if p in there]


def ads_off(tv, serial):
    mine = _mine(tv, serial)
    for item in ads_state(tv):
        if not item["off"]:
            out = tv.shell(f"pm disable-user --user 0 {item['package']}")
            if "disabled" in out:
                mine.add(item["package"])
    _save_mine(tv, serial, mine)
    return ads_state(tv, serial)


def ads_undo(tv, serial):
    """Switches back on what this setup switched off on this TV (and nothing else)."""
    for p in sorted(_mine(tv, serial)):
        tv.shell(f"pm enable {p}")
    _save_mine(tv, serial, set())
    return ads_state(tv, serial)


def _load_record():
    try:
        return json.loads(_record().read_text())
    except Exception:
        return {}


def serial(tv):
    return tv.prop("ro.serialno") or tv.ip


# ---- 5. undo everything ----

AMAZON_HOME = "com.amazon.tv.launcher"


def undo_plan(tv, serial):
    """What Undo everything would change on this TV, to show before it runs."""
    return {
        "app": app_state(tv),
        "ads_off": [a["what"] for a in ads_state(tv, serial) if a["off"]],
        "watcher_listed": _watcher_listed(tv),
    }


def undo_everything(tv, serial, progress=lambda f, msg=None: None):
    """Back to Amazon's own home: Couch TV out of the Home button and uninstalled (which also
    removes its grants), its watcher out of the accessibility list (others kept), and every ad
    and tracking app on the setup's list switched back on, whoever switched it off. Leaves
    everything else alone, including other launchers."""
    done = []
    progress(0.1, "Taking Couch TV off the Home button")
    cur = tv.shell("settings get secure enabled_accessibility_services").strip()
    if WATCHER in cur.split(":"):
        rest = [s for s in cur.split(":") if s and s != WATCHER and s != "null"]
        if rest:
            tv.shell(f"settings put secure enabled_accessibility_services '{':'.join(rest)}'")
        else:
            tv.shell("settings delete secure enabled_accessibility_services; settings put secure accessibility_enabled 0")
        done.append("watcher")
    progress(0.3, "Removing Couch TV")
    if app_state(tv).get("installed"):
        out = tv.shell(f"pm uninstall {PKG}", 120)
        if "Success" not in out:
            raise TvError("The TV did not remove Couch TV: " + out.strip()[-200:], "uninstall_failed")
        done.append("uninstalled")
    progress(0.6, "Switching Amazon's apps back on")
    back_on = []
    for item in ads_state(tv, serial):
        if item["off"]:
            tv.shell(f"pm enable {item['package']}")
            back_on.append(item["what"])
    _save_mine(tv, serial, set())
    tv.shell(f"rm -rf {TMP.rsplit('/', 1)[0]}/couchtv-setup*")
    progress(0.8, "Checking Amazon's home comes back")
    tv.shell("input keyevent KEYCODE_HOME")
    home = False
    for _ in range(8):
        time.sleep(1)
        if AMAZON_HOME in tv.shell("dumpsys activity activities 2>/dev/null | grep -m1 mResumedActivity"):
            home = True
            break
    progress(1.0, "Done")
    return {"changed": done, "back_on": back_on, "amazon_home": home, "other_watchers": other_watchers(tv)}
