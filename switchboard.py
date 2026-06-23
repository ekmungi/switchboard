#!/usr/bin/env python3
"""Thin entry-point shim: delegates to src/switchboard/cli.py so `python switchboard.py ...`,
the `sb` alias, and the /catalog slash command keep working unchanged."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))
from switchboard.cli import main
if __name__ == "__main__":
    main()
