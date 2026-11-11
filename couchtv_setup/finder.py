"""Finds Fire TV sticks on this Wi-Fi: anything answering on the ADB port (5555).

It only opens and closes a connection to each address, so the TV shows nothing and nothing
changes. Fire OS only opens port 5555 when ADB debugging is on.
"""
import ipaddress
import re
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

PORT = 5555


def _primary_ip():
    """The address this computer uses to reach other networks. Connecting a UDP socket only picks a
    route: nothing is sent."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))   # a documentation address, never really reached
            return sock.getsockname()[0]
    except OSError:
        return None


def _listed_ips():
    """Every IPv4 address the system lists: ifconfig on macOS and Linux, ipconfig on Windows."""
    if sys.platform == "win32":
        cmd, flags = ["ipconfig"], 0x08000000   # CREATE_NO_WINDOW: no console flashing up
    else:
        cmd, flags = ["ifconfig"], 0
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, creationflags=flags).stdout
    except Exception:
        return []
    return re.findall(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", out or "")


def local_networks():
    """The /24 networks this computer is on (Wi-Fi and wired), the one it uses first."""
    nets = []
    for raw in [_primary_ip()] + _listed_ips():
        try:
            ip = ipaddress.ip_address(raw)
        except (TypeError, ValueError):
            continue
        # private home addresses only: no 127.x, no 169.254.x, and masks such as 255.255.255.0
        # (Windows lists those next to the address) are not private, so they drop out too
        if ip.is_private and not ip.is_loopback and not ip.is_link_local and not str(ip).endswith(".0"):
            net = ipaddress.ip_network(f"{ip}/24", strict=False)
            if net not in nets:
                nets.append(net)
    return nets


def answers(ip, port=PORT, timeout=0.5):
    try:
        with socket.create_connection((str(ip), port), timeout=timeout):
            return True
    except OSError:
        return False


def scan(nets=None):
    hosts = [h for n in (nets or local_networks()) for h in n.hosts()]
    with ThreadPoolExecutor(max_workers=96) as pool:
        found = [str(h) for h, ok in zip(hosts, pool.map(answers, hosts)) if ok]
    return [{"ip": ip, "name": _name(ip)} for ip in found]


def _name(ip):
    try:
        return socket.gethostbyaddr(ip)[0].split(".")[0]
    except Exception:
        return None
