"""Finds Fire TV sticks on this Wi-Fi: anything answering on the ADB port (5555).

It only opens and closes a connection to each address, so the TV shows nothing and nothing
changes. Fire OS only opens port 5555 when ADB debugging is on.
"""
import ipaddress
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

PORT = 5555


def local_networks():
    """The /24 networks this Mac is on (Wi-Fi and wired), from ifconfig."""
    nets = []
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        out = ""
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "inet" and not parts[1].startswith("127."):
            ip = ipaddress.ip_address(parts[1])
            if ip.is_private and not ip.is_link_local:
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
