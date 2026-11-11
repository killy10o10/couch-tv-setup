"""Finding the home network from what the system lists, on macOS and on Windows."""
import ipaddress
import unittest
from unittest import mock

from couchtv_setup import finder

IPCONFIG = """
Windows IP Configuration

Wireless LAN adapter Wi-Fi:

   Connection-specific DNS Suffix  . : home
   Link-local IPv6 Address . . . . . : fe80::1c2d:3e4f:5a6b:7c8d%12
   IPv4 Address. . . . . . . . . . . : 192.168.1.37
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : 192.168.1.1

Ethernet adapter vEthernet (WSL):

   IPv4 Address. . . . . . . . . . . : 172.29.240.1
   Subnet Mask . . . . . . . . . . . : 255.255.240.0

Ethernet adapter Bluetooth Network Connection:

   Media State . . . . . . . . . . . : Media disconnected
   Autoconfiguration IPv4 Address. . : 169.254.10.20
"""

IFCONFIG = """
lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
	inet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
	inet 192.168.100.132 netmask 0xffffff00 broadcast 192.168.100.255
"""


def nets(text, primary):
    with mock.patch.object(finder, "_primary_ip", return_value=primary), \
            mock.patch.object(finder.subprocess, "run", return_value=mock.Mock(stdout=text)):
        return [str(n) for n in finder.local_networks()]


class Finder(unittest.TestCase):
    def test_windows_ipconfig(self):
        found = nets(IPCONFIG, "192.168.1.37")
        self.assertEqual(found[0], "192.168.1.0/24")            # the one in use comes first
        self.assertNotIn("169.254.10.0/24", found)               # no self-assigned addresses
        self.assertFalse(any(n.startswith("255.") for n in found))  # masks are not networks

    def test_mac_ifconfig(self):
        self.assertEqual(nets(IFCONFIG, None), ["192.168.100.0/24"])

    def test_nothing_listed_still_uses_the_primary(self):
        self.assertEqual(nets("", "10.0.0.8"), ["10.0.0.0/24"])

    def test_networks_are_real(self):
        for n in nets(IPCONFIG, "192.168.1.37"):
            ipaddress.ip_network(n)


if __name__ == "__main__":
    unittest.main()
