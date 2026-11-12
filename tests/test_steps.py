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
        self.record = ""
        self.focus = 0            # the setup screen opens with Connect ADB highlighted
        self.screen_ok = True     # False: the screen cannot be read
        self.ops = {"SYSTEM_ALERT_WINDOW", "GET_USAGE_STATS"}   # appops already allowed
        self.front = "com.amazon.tv.launcher/.ui.HomeActivity_vNext"

    def _app_starts_watcher(self):
        """The app switches its watcher on when it starts or the home button is pressed, once it
        has the grant and "Use as home screen" is on."""
        if self.grant and self.home and WATCHER not in self.a11y:
            self.a11y = WATCHER if self.a11y == "null" else self.a11y + ":" + WATCHER
            self.bound = True

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
            return "java.lang.SecurityException: Shell cannot change component state"   # as Fire OS
        if cmd.startswith("uiautomator dump"):
            if not self.screen_ok:
                return ""
            names = ["Connect ADB", "New phone code", "Developer options",
                     "Stop being the home screen" if self.home else "Use as home screen", "Forget phones"]
            return "".join(f'<node class="android.widget.Button" package="dev.couchtv.ontv" text="{n}" '
                           f'focused="{str(i == self.focus).lower()}" />' for i, n in enumerate(names))
        if cmd == "input keyevent KEYCODE_DPAD_RIGHT":
            self.focus = min(self.focus + 1, 4)
        if cmd == "input keyevent KEYCODE_DPAD_LEFT":
            self.focus = max(self.focus - 1, 0)
        if cmd == "input keyevent KEYCODE_DPAD_CENTER":
            self.pressed = getattr(self, "pressed", []) + [self.focus]
            if self.focus == 3:
                self.home = not self.home
                self._app_starts_watcher()
        if cmd.startswith("appops get"):
            op = cmd.split()[-1]
            return f"{op}: allow\n" if op in self.ops else "No operations.\n"
        if cmd.startswith("appops set"):
            self.ops.add(cmd.split()[-2])
        if cmd == "am start -a android.settings.SETTINGS":
            self.front = "com.amazon.tv.settings.v2/.tv.SettingsActivity"
        if cmd == "input keyevent KEYCODE_HOME":
            # Home does nothing while a home screen is already in front
            if "launcher" not in self.front and "dev.couchtv.ontv" not in self.front:
                self.front = "dev.couchtv.ontv/.HomeActivity" if self.home and self.bound else "com.amazon.tv.launcher/.ui.HomeActivity_vNext"
        if cmd.startswith("am force-stop"):
            self.focus = 0            # the setup screen opens with Connect ADB highlighted
            self._app_starts_watcher()
        if cmd == "settings get secure enabled_accessibility_services":
            return self.a11y + "\n"
        if cmd.startswith("settings put secure enabled_accessibility_services"):
            self.a11y = cmd.split("'")[1]
            self.bound = True
        if cmd.startswith("dumpsys accessibility"):
            # as Fire OS prints it: one service per line, another launcher's first
            couch = "\n                     Service[label=Couch TV home watch]" if self.bound else ""
            return ("     Bound services:{Service[label=Projectivy Launcher]," + couch + "}\n"
                    "     Enabled services:{{dev.couchtv.ontv/dev.couchtv.ontv.WatchService}}\n")
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
        if cmd.startswith("cat " + steps.TV_RECORD):
            return self.record
        if "printf" in cmd and steps.TV_RECORD in cmd:
            self.record = "\n".join(cmd.split("printf '%s\\n' ")[1].split(" > ")[0].split()) + "\n"
        if cmd.startswith("rm -f " + steps.TV_RECORD):
            self.record = ""
        if cmd.startswith("pm uninstall"):
            self.installed = False
            return "Success"
        if cmd.startswith("settings delete secure enabled_accessibility_services"):
            self.a11y = "null"
        if "mResumedActivity" in cmd:
            return "mResumedActivity: ActivityRecord{1 u0 " + self.front + "}"
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

    def test_use_as_home_is_pressed_never_forget_phones(self):
        tv = FakeTv(grant=True)
        r = steps.make_home(tv)
        self.assertTrue(r["home_on"])
        self.assertEqual(tv.pressed, [3])            # select pressed once, on Use as home screen

    def test_unreadable_screen_asks_the_person(self):
        tv = FakeTv(grant=True)
        tv.screen_ok = False
        r = steps.make_home(tv)
        self.assertFalse(r["home_on"])
        self.assertFalse(getattr(tv, "pressed", []))  # nothing pressed blind

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

    def test_undo_from_another_computer_uses_the_tv_record(self):
        tv = FakeTv()
        steps.ads_off(tv, "G070VM")
        self.assertTrue(tv.record)
        steps._record().unlink()                     # a different Mac: no record of its own
        self.assertTrue(all(a["mine"] for a in steps.ads_state(tv, "G070VM")))
        steps.ads_undo(tv, "G070VM")
        self.assertEqual(tv.disabled, set())
        self.assertEqual(tv.record, "")

    def test_undo_everything(self):
        other = "com.spocky.projengmenu/.services.ProjectivyAccessibilityService"
        tv = FakeTv(grant=True, home=True, a11y=other + ":" + WATCHER, bound=True,
                    disabled={p for p, _ in steps.ADS})
        r = steps.undo_everything(tv, "G070VM")
        self.assertFalse(tv.installed)
        self.assertEqual(tv.a11y, other)             # the other launcher's service is kept
        self.assertEqual(tv.disabled, set())         # every ad app back on, whoever switched it off
        self.assertTrue(r["amazon_home"])
        self.assertNotIn("com.amazon.tv.launcher", " ".join(c for c in tv.log if c.startswith("pm ")))

    def test_undo_everything_alone_watcher_clears_the_list(self):
        tv = FakeTv(grant=True, home=True, a11y=WATCHER, bound=True)
        steps.undo_everything(tv, "G070VM")
        self.assertEqual(tv.a11y, "null")

    def test_missing_usage_grant_is_given(self):
        tv = FakeTv(grant=True, home=True, a11y=WATCHER, bound=True)
        tv.ops = {"SYSTEM_ALERT_WINDOW"}
        r = steps.make_home(tv)
        self.assertEqual(r["changed"], ["usage"])
        self.assertIn("appops set dev.couchtv.ontv GET_USAGE_STATS allow", tv.log)

    def test_home_check_leaves_amazons_home_first(self):
        # Amazon's home in front: pressing Home alone would prove nothing
        tv = FakeTv(grant=True, home=True, a11y=WATCHER, bound=True)
        self.assertTrue(steps.press_home_check(tv)["ok"])
        self.assertLess(tv.log.index("am start -a android.settings.SETTINGS"), tv.log.index("input keyevent KEYCODE_HOME"))

    def test_home_check_fails_without_couch_tv(self):
        tv = FakeTv(grant=True, home=False)
        self.assertFalse(steps.press_home_check(tv)["ok"])

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
