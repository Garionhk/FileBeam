#!/usr/bin/env python3
"""Convenience launcher: `python run.py` (same as `python -m filebeam.main`)."""
from filebeam.main import main

if __name__ == "__main__":
    raise SystemExit(main())
