#!/usr/bin/env python3
"""Panoptes MCP entrypoint for Claude Desktop, Cursor, and other MCP hosts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.mcp.server import main


if __name__ == "__main__":
    main()
