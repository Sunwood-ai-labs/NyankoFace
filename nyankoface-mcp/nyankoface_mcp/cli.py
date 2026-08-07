from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import __version__
from .stdio import ConfigurationError, StdioSettings, run_stdio


def _settings() -> StdioSettings:
    try:
        return StdioSettings.from_env()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def stdio_main() -> None:
    settings = _settings()
    try:
        asyncio.run(run_stdio(settings))
    except KeyboardInterrupt:
        return
    except Exception:
        print("NyankoFace MCP stdio adapter stopped unexpectedly", file=sys.stderr)
        raise SystemExit(1) from None


def http_main() -> None:
    import uvicorn

    from .config import Settings
    from .server import create_http_app

    settings = Settings.from_env()
    uvicorn.run(create_http_app(settings), host="0.0.0.0", port=settings.listen_port)


def admin_main() -> None:
    import uvicorn

    from .admin_http import AdminSettings, create_admin_app

    settings = AdminSettings.from_env()
    uvicorn.run(create_admin_app(settings), host="0.0.0.0", port=settings.listen_port,
                access_log=False)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nyankoface-mcp")
    parser.add_argument("--version", action="version", version=f"nyankoface-mcp {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("stdio", help="bridge local stdio to the remote Streamable HTTP endpoint")
    subcommands.add_parser("serve-http", help="run the official Streamable HTTP server")
    subcommands.add_parser("validate-config", help="validate stdio environment without exposing secrets")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "stdio":
        stdio_main()
    elif args.command == "serve-http":
        http_main()
    else:
        settings = _settings()
        print(json.dumps({
            "valid": True,
            "remote_url": settings.remote_url,
            "token_source": (
                "NYANKOFACE_MCP_CLIENT_TOKEN_FILE"
                if __import__("os").getenv("NYANKOFACE_MCP_CLIENT_TOKEN_FILE")
                else "NYANKOFACE_MCP_TOKEN"
            ),
            "ca_bundle_configured": settings.ca_bundle is not None,
        }, separators=(",", ":")))
