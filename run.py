"""Launch the Panoptes web application."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.web.helpers import load_env

load_env()


def main() -> None:
    parser = argparse.ArgumentParser(description="Panoptes — demand radar web app")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default 8000)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    args = parser.parse_args()

    import uvicorn

    print(f"Panoptes web app -> http://{args.host}:{args.port}")
    uvicorn.run(
        "app.web.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
