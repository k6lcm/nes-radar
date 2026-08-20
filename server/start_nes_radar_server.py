#!/usr/bin/env python3
"""Source launcher for NES Radar Server 0.4.3."""

from pathlib import Path
import runpy
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
runpy.run_path(str(ROOT / "src" / "nes_radar_server.py"), run_name="__main__")
