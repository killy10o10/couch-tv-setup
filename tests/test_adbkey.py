"""The ADB key pair made without the `cryptography` package is the same format adb uses."""
import base64
import os
import tempfile
import unittest

from adb_shell.auth.sign_pythonrsa import PythonRSASigner, _load_rsa_private_key

from couchtv_setup import adbkey


class AdbKey(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "adbkey")
        adbkey.keygen(self.path)

    def test_the_signer_loads_it_and_signs(self):
        signer = PythonRSASigner(open(self.path + ".pub").read(), open(self.path).read())
        self.assertEqual(len(signer.Sign(b"\x01" * 20)), 256)

    def test_public_key_matches_the_private_key(self):
        priv = _load_rsa_private_key(open(self.path).read())
        pub = base64.b64decode(open(self.path + ".pub").read().split()[0])
        self.assertEqual(pub, adbkey.android_pubkey(priv.n, priv.e))
        self.assertEqual(len(pub), 524)   # sizeof(struct RSAPublicKey) for a 2048-bit key

    @unittest.skipUnless(__import__("importlib").util.find_spec("cryptography"), "cryptography not installed")
    def test_same_as_adb_shells_own_encoder(self):
        from adb_shell.auth import keygen as reference
        self.assertEqual(reference.encode_pubkey(self.path),
                         base64.b64decode(open(self.path + ".pub").read().split()[0]))


if __name__ == "__main__":
    unittest.main()
