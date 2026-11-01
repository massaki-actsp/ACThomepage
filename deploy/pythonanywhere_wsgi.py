"""Copy this content into the WSGI configuration file linked on the Web tab."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(os.getenv("ACTSP_PROJECT_PATH", str(Path.home() / "ACThomepage"))).resolve()
if not (PROJECT_DIR / "app.py").is_file():
    raise RuntimeError("Ajuste PROJECT_DIR para a pasta ACThomepage no PythonAnywhere.")
sys.path.insert(0, str(PROJECT_DIR))
load_dotenv(PROJECT_DIR / ".env")

from wsgi import application  # noqa: E402, F401
