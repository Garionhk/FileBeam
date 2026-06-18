#!/usr/bin/env python3
"""Convenience launcher: `python run.py` (same as `python -m fileshare.main`)."""
from fileshare.main import main

if __name__ == "__main__":
    raise SystemExit(main())
