"""Run the demo: ``python -m taxng`` (from the backend directory)."""

from __future__ import annotations

import argparse
import logging

import uvicorn

from .api.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="tax.ng Phase 1 demo server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
