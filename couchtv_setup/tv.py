"""Talking to the TV over ADB, in pure Python (adb-shell), so no Google adb install is needed.

The connection, retry and copy code is adapted from couch-tv's tv-home/tools/tvadb.py
(MIT License, Copyright (c) 2026 Seagey).
"""
import base64
import hashlib
import io
import os
import time

from adb_shell.adb_device import AdbDeviceTcp
from adb_shell.auth.keygen import keygen
from adb_shell.auth.sign_pythonrsa import PythonRSASigner

from . import paths

TMP = "/data/local/tmp/couchtv-setup"
PART = 64 * 1024       # adb push part size
B64_STEP = 32 * 1024   # base64 characters per shell command (a multiple of 4)
TRIES = 3


class TvError(Exception):
    """A problem to show the person as it is: plain words, no traceback."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def signer():
    key = os.environ.get("COUCHTV_SETUP_ADBKEY") or str(paths.data() / "adbkey")
    if not os.path.exists(key):
        keygen(key)
    with open(key + ".pub") as pub, open(key) as priv:
        return PythonRSASigner(pub.read(), priv.read())


class Tv:
    """An ADB connection that reconnects and tries again when the TV stops answering."""

    def __init__(self, ip, port=5555, allow_wait_s=90):
        self.ip, self.port = ip, port
        self.dev = None
        self._open(allow_wait_s)

    def _open(self, allow_wait_s=15):
        dev = AdbDeviceTcp(self.ip, self.port, default_transport_timeout_s=allow_wait_s)
        try:
            # The first time, the TV asks "Allow USB debugging?": this waits for the press.
            dev.connect(rsa_keys=[signer()], auth_timeout_s=allow_wait_s)
        except Exception as e:
            raise TvError(
                "The TV did not let this computer in. Check that ADB debugging is on, then press Allow "
                "on the TV (tick Always allow) and try again.", "not_allowed") from e
        self.dev = dev

    def close(self):
        try:
            if self.dev:
                self.dev.close()
        except Exception:
            pass

    def reconnect(self):
        self.close()
        time.sleep(2)
        self._open()

    def _retry(self, fn):
        last = None
        for attempt in range(TRIES):
            try:
                return fn()
            except TvError:
                raise
            except Exception as e:
                last = e
                if attempt + 1 < TRIES:
                    try:
                        self.reconnect()
                    except Exception as e2:
                        last = e2
        raise TvError(f"The TV stopped answering ({type(last).__name__}). Is it still on?", "lost")

    def shell(self, cmd, timeout_s=60):
        return self._retry(lambda: self.dev.shell(cmd, timeout_s=timeout_s, read_timeout_s=timeout_s)) or ""

    def prop(self, name):
        return self.shell(f"getprop {name}").strip()

    # ---- copying and installing an app ----

    def _md5(self, path):
        return (self.shell(f"md5sum {path} 2>/dev/null || toybox md5sum {path}").split() or [""])[0]

    def _push(self, data, dest, progress):
        self.shell(f"rm -rf {TMP}.parts {dest}; mkdir -p {TMP}.parts")
        for i in range(0, len(data), PART):
            self.dev.push(io.BytesIO(data[i:i + PART]), f"{TMP}.parts/{i // PART:05d}",
                          transport_timeout_s=20, read_timeout_s=20)
            progress(min(1.0, (i + PART) / len(data)))
        self.shell(f"cat {TMP}.parts/* > {dest}; rm -rf {TMP}.parts", 120)

    def _push_b64(self, data, dest, progress):
        b64 = base64.b64encode(data).decode()
        self.shell(f"rm -rf {TMP}.b64 {dest}; mkdir -p {TMP}.b64")
        total = (len(b64) + B64_STEP - 1) // B64_STEP
        for n, i in enumerate(range(0, len(b64), B64_STEP), 1):
            self.shell(f"echo -n '{b64[i:i + B64_STEP]}' > {TMP}.b64/{n:05d}")
            progress(n / total)
        self.shell(f"cat {TMP}.b64/* | base64 -d > {dest}; rm -rf {TMP}.b64", 120)

    def install(self, apk_path, progress=lambda f: None):
        """Copies the app to the TV (adb push, or base64 text if push stalls), checks it, installs.
        Returns pm's answer; raises TvError with code "different_key" when the TV has the same app
        signed with another key."""
        with open(apk_path, "rb") as f:
            data = f.read()
        want = hashlib.md5(data).hexdigest()
        dest = TMP + ".apk"
        ok = False
        try:
            self._push(data, dest, progress)
            ok = self._md5(dest) == want
        except TvError:
            raise
        except Exception:
            self.reconnect()
        if not ok:
            self._push_b64(data, dest, progress)
            if self._md5(dest) != want:
                self.shell(f"rm -f {dest}")
                raise TvError("The app reached the TV damaged. Try again.", "damaged")
        out = self.shell(f"pm install -r {dest}; rm -f {dest}", 180)
        if "Success" in out:
            return out
        if "UPDATE_INCOMPATIBLE" in out or "SIGNATURES" in out:
            raise TvError("This TV already has a Couch TV app made by someone else (a different "
                          "signing key), so it cannot be updated in place.", "different_key")
        if "INSUFFICIENT_STORAGE" in out:
            raise TvError("The TV is out of space. Remove an app you do not use and try again.", "no_space")
        raise TvError("The TV did not install the app: " + out.strip()[-200:], "install_failed")
