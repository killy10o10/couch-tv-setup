"""Makes this computer's ADB key pair with the pure-Python `rsa` package.

adb-shell's own `keygen` needs the `cryptography` package, which is compiled code: its newer
versions no longer ship a ready-made build for Intel Macs, and a self-built one clashes with the
OpenSSL PyInstaller bundles (the Intel app crashed on start). The signing adb-shell does at every
connection (`PythonRSASigner`) already uses `rsa`, so only the one-off key making is replaced here.

The files are in the same formats Google's adb writes:
- `adbkey`: the private key, PEM-encoded PKCS#8 ("BEGIN PRIVATE KEY")
- `adbkey.pub`: Android's own RSAPublicKey struct, base64-encoded, then " user@host"
"""
import base64
import os
import socket
import struct

import rsa
from pyasn1.codec.der import encoder
from pyasn1.type import namedtype, univ

MODULUS_SIZE = 2048 // 8                      # bytes
MODULUS_WORDS = MODULUS_SIZE // 4
PUBKEY_STRUCT = "<LL{0}s{0}sL".format(MODULUS_SIZE)   # struct RSAPublicKey in Android's adb
RSA_OID = "1.2.840.113549.1.1.1"              # rsaEncryption


class _AlgorithmIdentifier(univ.Sequence):
    componentType = namedtype.NamedTypes(
        namedtype.NamedType("algorithm", univ.ObjectIdentifier()),
        namedtype.NamedType("parameters", univ.Null()),
    )


class _PrivateKeyInfo(univ.Sequence):        # PKCS#8, RFC 5208
    componentType = namedtype.NamedTypes(
        namedtype.NamedType("version", univ.Integer()),
        namedtype.NamedType("privateKeyAlgorithm", _AlgorithmIdentifier()),
        namedtype.NamedType("privateKey", univ.OctetString()),
    )


def pkcs8_pem(priv):
    """An `rsa.PrivateKey` as PEM-encoded PKCS#8, the way adb stores it."""
    alg = _AlgorithmIdentifier()
    alg["algorithm"] = univ.ObjectIdentifier(RSA_OID)
    alg["parameters"] = univ.Null("")
    info = _PrivateKeyInfo()
    info["version"] = 0
    info["privateKeyAlgorithm"] = alg
    info["privateKey"] = univ.OctetString(priv.save_pkcs1(format="DER"))
    return rsa.pem.save_pem(encoder.encode(info), "PRIVATE KEY")


def android_pubkey(n, e):
    """The public key in Android's RSAPublicKey layout (what the TV stores and shows as "Always
    allow from this computer")."""
    r32 = 1 << 32
    n0inv = r32 - pow(n % r32, -1, r32)        # -1 / n mod 2^32, as Android's adb computes it
    rr = pow(1 << (MODULUS_SIZE * 8), 2, n)
    return struct.pack(PUBKEY_STRUCT, MODULUS_WORDS, n0inv,
                       n.to_bytes(MODULUS_SIZE, "little"), rr.to_bytes(MODULUS_SIZE, "little"), e)


def _who():
    try:
        user = os.getlogin() or "user"
    except OSError:
        user = "user"
    return f" {user}@{socket.gethostname() or 'computer'}"


def keygen(path):
    """Writes `path` (private) and `path`.pub (public), like adb-shell's keygen."""
    pub, priv = rsa.newkeys(2048)
    with open(path, "wb") as f:
        f.write(pkcs8_pem(priv))
    with open(path + ".pub", "wb") as f:
        f.write(base64.b64encode(android_pubkey(pub.n, pub.e)) + _who().encode())
