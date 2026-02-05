from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP

from hydra_mcp.tools import register_tools


def build_server() -> FastMCP:
    mcp = FastMCP(
        name="Hydra",
        instructions="Hydra MCP server (stdio). Wraps hydra.py as Claude Code MCP tools.",
    )
    register_tools(mcp)
    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hydra-mcp")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport to use (default: stdio).",
    )
    args = parser.parse_args(argv)

    mcp = build_server()
    mcp.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

