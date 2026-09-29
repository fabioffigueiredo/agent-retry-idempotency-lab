"""Command-line entry point for ``python -m agent_retry_lab``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .demo import run_demo
from .web import serve


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent_retry_lab")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo_parser = subparsers.add_parser("demo", help="generate local demo artifacts")
    demo_parser.add_argument("--output-dir", required=True)
    serve_parser = subparsers.add_parser("serve", help="serve the local browser demo")
    serve_parser.add_argument("--database", required=True)
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    arguments = parser.parse_args(argv)

    if arguments.command == "demo":
        run_demo(arguments.output_dir)
    elif arguments.command == "serve":
        serve(arguments.database, arguments.host, arguments.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
