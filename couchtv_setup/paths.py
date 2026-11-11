"""Where the setup keeps its own files: its ADB key, the downloaded app, and the undo list.

macOS: ~/Library/Application Support/Couch TV Setup and ~/Library/Caches/Couch TV Setup.
Windows: %APPDATA%\\Couch TV Setup and %LOCALAPPDATA%\\Couch TV Setup\\Cache.
Linux (from source): ~/.local/share/couch-tv-setup and ~/.cache/couch-tv-setup.
"""
import os
import sys
from pathlib import Path

APP = "Couch TV Setup"


def _base_data():
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "couch-tv-setup"


def _base_cache():
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP / "Cache"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "couch-tv-setup"


def data():
    p = Path(os.environ.get("COUCHTV_SETUP_HOME") or _base_data())
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache():
    p = _base_cache()
    p.mkdir(parents=True, exist_ok=True)
    return p
