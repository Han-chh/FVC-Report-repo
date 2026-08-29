#!/usr/bin/env python3
"""Compatibility entry point: prepare the 2021 cloud assets in GEE."""
from pathlib import Path
import os
import sys

script = Path(__file__).with_name("02_prepare_gee_cloud_data.py")
os.execv(sys.executable, [sys.executable, str(script), "--year", "2021", *sys.argv[1:]])
