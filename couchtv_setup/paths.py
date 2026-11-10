"""Where the setup keeps its own files: its ADB key, the downloaded app, and the undo list."""
import os
from pathlib import Path

APP = "Couch TV Setup"


def data():
    p = Path(os.environ.get("COUCHTV_SETUP_HOME") or Path.home() / "Library" / "Application Support" / APP)
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache():
    p = Path.home() / "Library" / "Caches" / APP
    p.mkdir(parents=True, exist_ok=True)
    return p
