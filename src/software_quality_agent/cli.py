from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Software Quality Agent")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Run the HTTP server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8010, type=int)
    serve.add_argument("--reload", action="store_true")

    args = parser.parse_args()
    if args.command in (None, "serve"):
        uvicorn.run(
            "software_quality_agent.server:app",
            host=getattr(args, "host", "127.0.0.1"),
            port=getattr(args, "port", 8010),
            reload=getattr(args, "reload", False),
        )


if __name__ == "__main__":  # pragma: no cover
    main()

