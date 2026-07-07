#!/usr/bin/env python3
"""search.py — thin re-export. Use python -m src.index.search directly."""
import sys
from src.index.search import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
