#!/usr/bin/env python3
"""Stands in for the `claude` command in tests: fake_codex.py, answering as Claude Code would."""

import os
import runpy
from pathlib import Path

os.environ["FAKE_AS"] = "claude"
runpy.run_path(str(Path(__file__).with_name("fake_codex.py")), run_name="__main__")
