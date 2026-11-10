"""The steps against a pretend TV: each command the TV gets is recorded, so the tests can check
that a TV that is already set up is left alone, and a new one gets exactly what it needs."""
import os
import tempfile
import unittest
from unittest import mock

os.environ["COUCHTV_SETUP_HOME"] = tempfile.mkdtemp()

from couchtv_setup import steps  # noqa: E402

WATCHER = "dev.couchtv.ontv/dev.couchtv.ontv.WatchService"
INSTALLED = """Packages:
  Package [dev.couchtv.ontv] (abc):
    versionName=0.12
    runtime permissions:
      android.permission.WRITE_SECURE_SETTINGS: granted={grant}
{enabled}
"""


class FakeTv:
    def __init__(self, installed=True, grant=False, home=False, a11y="null", bound=False, disabled=()):
        self.ip = "192.168.1.9"
        self.installed, self.grant, self.home, self.a11y, self.bound = installed, grant, home, a11y, bound
        self.disabled = set(disabled)
        self.log = []

    def prop(self, name):
        return {"ro.product.model": "AFTKM", "ro.product.manufacturer": "Amazon",
                "ro.build.version.name": "Fire OS 8.1.8.5", "ro.build.version.sdk": "30",
                "ro.serialno": "G070VM"}.get(name, "")

    def shell(self, cmd, timeout_s=60):
        self.log.append(cmd)
        if cmd.startswith("dumpsys package"):
            if not self.installed:
                return "Unable to find package"
            enabled = "    enabledComponents:\n      dev.couchtv.ontv.HomeAlias\n" if self.home else ""
            return INSTALLED.format(grant=str(self.grant).lower(), enabled=enabled)
        if cmd.startswith("pm grant"):
            self.grant = True
        if cmd.startswith("pm enable dev.couchtv.ontv/.HomeAlias"):
            self.home = True
        if cmd.startswith("appops get"):
            return "SYSTEM_ALERT_WINDOW: allow\n"
        if cmd.startswith("am force-stop") and self.grant and self.home:
            # the app switches its watcher on when it starts
            self.a11y = WATCHER if self.a11y == "null" else self.a11y + ":" + WATCHER
            self.bound = True
        if cmd == "settings get secure enabled_accessibility_services":
            return self.a11y + "\n"
        if cmd.startswith("settings put secure enabled_accessibility_services"):
            self.a11y = cmd.split("'")[1]
            self.bound = True
        if cmd.startswith("dumpsys accessibility"):
            return "Bound services:{Service[label=Couch TV home watch]}" if self.bound else "Bound services:{}"
        if cmd == "pm list packages -d":
            return "".join(f"package:{p}\n" for p in self.disabled)
        if cmd == "pm list packages":
            return "".join(f"package:{p}\n" for p, _ in steps.ADS) + "package:com.amazon.tv.launcher\n"
        if cmd.startswith("pm disable-user"):
            p = cmd.split()[-1]
            self.disabled.add(p)
            return f"Package {p} new state: disabled-user"
        if cmd.startswith("pm enable "):
            self.disabled.discard(cmd.split()[-1])
        return ""


@mock.patch("time.sleep", lambda s: None)
class Steps(unittest.TestCase):
    def test_device(self):
        d = steps.device(FakeTv(installed=False))
        self.assertEqual(d["name"], "Fire TV Stick 4K (2nd gen)")
        self.assertTrue(d["supported"])
        self.assertFalse(d["app"]["installed"])

    def test_new_tv_gets_everything(self):
        tv = FakeTv()
        r = steps.make_home(tv)
        self.assertEqual(r["changed"], ["grant", "home"])
        self.assertTrue(r["watcher_running"])
        self.assertIn("pm grant dev.couchtv.ontv android.permission.WRITE_SECURE_SETTINGS", tv.log)

    def test_set_up_tv_is_left_alone(self):
        tv = FakeTv(grant=True, home=True, a11y="com.other/.Svc:" + WATCHER, bound=True)
        r = steps.make_home(tv)
        self.assertEqual(r["changed"], [])
        self.assertFalse([c for c in tv.log if c.startswith(("pm ", "settings put", "am "))])

    def test_watcher_added_when_the_app_did_not(self):
        tv = FakeTv(grant=True, home=True, a11y="com.other/.Svc")
        r = steps.make_home(tv)
        self.assertEqual(r["changed"], ["watcher"])
        self.assertEqual(tv.a11y, "com.other/.Svc:" + WATCHER)   # kept the other one

    def test_ads_off_and_undo_only_touch_what_it_switched_off(self):
        before = steps.ADS[0][0]
        tv = FakeTv(disabled={before})
        state = steps.ads_off(tv, "G070VM")
        self.assertTrue(all(a["off"] for a in state))
        self.assertFalse(next(a for a in state if a["package"] == before)["mine"])
        steps.ads_undo(tv, "G070VM")
        self.assertEqual(tv.disabled, {before})
        self.assertNotIn("com.amazon.tv.launcher", " ".join(tv.log))

    def test_restart_is_sent_once_even_when_the_tv_drops(self):
        class Dev:
            calls = 0
            def shell(self, *a, **k):
                Dev.calls += 1
                raise TimeoutError
            def close(self):
                pass
        tv = FakeTv()
        tv.dev = Dev()
        tv.close = lambda: None
        steps.restart(tv)
        self.assertEqual(Dev.calls, 1)


if __name__ == "__main__":
    unittest.main()
