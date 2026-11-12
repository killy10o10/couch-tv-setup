"""The Couch TV download is only used when its SHA-256 matches what GitHub lists for it."""
import hashlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from couchtv_setup import steps
from couchtv_setup.tv import TvError

APK = b"PK\x03\x04 pretend apk" * 1000


class Reply(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def release(digest):
    asset = {"name": steps.APK_NAME, "size": len(APK), "browser_download_url": "https://example.invalid/a.apk"}
    if digest is not None:
        asset["digest"] = digest
    return {"tag_name": "v9.9", "assets": [asset]}


class Download(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        os.environ.pop("COUCHTV_APK", None)
        p = mock.patch.object(steps.paths, "cache", return_value=__import__("pathlib").Path(self.dir.name))
        p.start()
        self.addCleanup(p.stop)

    def run_with(self, rel, body=APK):
        replies = iter([Reply(json.dumps(rel).encode()), Reply(body)])
        with mock.patch.object(steps, "_open", side_effect=lambda *a, **k: next(replies)):
            return steps.download()

    def test_matching_download_is_kept(self):
        r = self.run_with(release("sha256:" + hashlib.sha256(APK).hexdigest()))
        self.assertEqual(open(r["path"], "rb").read(), APK)

    def test_changed_download_is_thrown_away(self):
        with self.assertRaises(TvError) as e:
            self.run_with(release("sha256:" + hashlib.sha256(APK).hexdigest()), body=APK[:-1] + b"X")
        self.assertEqual(e.exception.code, "bad_download")
        self.assertEqual(os.listdir(self.dir.name), [])

    def test_no_digest_is_refused(self):
        with self.assertRaises(TvError) as e:
            self.run_with(release(None))
        self.assertEqual(e.exception.code, "no_digest")

    def test_cached_copy_is_checked_too(self):
        good = "sha256:" + hashlib.sha256(APK).hexdigest()
        (__import__("pathlib").Path(self.dir.name) / "couch-tv-ontv-v9.9.apk").write_bytes(b"x" * len(APK))  # same size, wrong file
        r = self.run_with(release(good))
        self.assertEqual(open(r["path"], "rb").read(), APK)


if __name__ == "__main__":
    unittest.main()
