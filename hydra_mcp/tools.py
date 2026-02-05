from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Sequence

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_text(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _tool_ok(result: Any) -> dict[str, Any]:
    return {"ok": True, "result": result, "ts": _iso_now()}


@dataclass(frozen=True)
class MCPError(Exception):
    code: str
    message: str
    data: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            out["data"] = self.data
        return out


def _tool_error(err: MCPError) -> CallToolResult:
    payload = err.to_dict()
    return CallToolResult(
        isError=True,
        structuredContent=payload,
        content=[TextContent(type="text", text=_json_text(payload))],
    )


def _tool_success(payload: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        isError=False,
        structuredContent=payload,
        content=[TextContent(type="text", text=_json_text(payload))],
    )


def _run_git(path: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(path),
        text=True,
        capture_output=True,
        check=False,
    )


def _git_toplevel(path: Path) -> Path:
    proc = _run_git(path, ["rev-parse", "--show-toplevel"])
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        raise MCPError("INVALID_ARG", f"Not a git repository: {path}")
    return Path(proc.stdout.strip()).expanduser().resolve()


@contextlib.contextmanager
def _pushd(path: Path):
    prev = Path.cwd()
    os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(str(prev))


@dataclass
class _State:
    project_root: Path | None = None


_STATE = _State()
_HYDRA_CACHE: ModuleType | None = None


def _hydra_py_path() -> Path:
    # Repo root is one level above this package directory.
    return (Path(__file__).resolve().parents[1] / "hydra.py").resolve()


def _load_hydra() -> ModuleType:
    global _HYDRA_CACHE
    if _HYDRA_CACHE is not None:
        return _HYDRA_CACHE

    hydra_path = _hydra_py_path()
    if not hydra_path.is_file():
        raise MCPError("NOT_FOUND", "hydra.py not found next to hydra_mcp package", {"hydraPath": str(hydra_path)})

    mod_name = f"hydra_mcp_hydra_{hashlib.sha1(str(hydra_path).encode('utf-8')).hexdigest()[:12]}"
    spec = importlib.util.spec_from_file_location(mod_name, str(hydra_path))
    if spec is None or spec.loader is None:
        raise MCPError("INTERNAL", f"Failed to import hydra.py from {hydra_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    _HYDRA_CACHE = mod
    return mod


def _require_project_root(project_root: str | None = None) -> Path:
    if project_root is not None:
        root_in = Path(project_root).expanduser()
        if not root_in.is_absolute():
            raise MCPError("INVALID_ARG", "projectRoot must be an absolute path", {"projectRoot": project_root})
        if not root_in.exists() or not root_in.is_dir():
            raise MCPError("INVALID_ARG", "projectRoot must be an existing directory", {"projectRoot": project_root})
        root = _git_toplevel(root_in)
        _STATE.project_root = root
        return root

    if _STATE.project_root is not None:
        return _STATE.project_root

    # Fallback: infer from current working directory of the server process.
    root = _git_toplevel(Path.cwd())
    _STATE.project_root = root
    return root


def _capture_hydra_main(hydra: ModuleType, argv: Sequence[str], *, cwd: Path) -> tuple[int, str, str]:
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    with _pushd(cwd), contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        code = int(hydra.main(list(argv)))  # type: ignore[attr-defined]
    return code, stdout_buf.getvalue(), stderr_buf.getvalue()


def _maybe_install_hydra_py(project_root: Path, *, force: bool = False) -> dict[str, Any]:
    src = _hydra_py_path()
    dst = (project_root / "hydra.py").resolve()
    if dst.exists() and not force:
        return {"installed": False, "reason": "already-exists", "path": str(dst)}
    if dst.exists() and dst.is_dir():
        raise MCPError("CONFLICT", "Project hydra.py path is a directory", {"path": str(dst)})

    # Prefer a relative symlink for portability.
    try:
        if dst.exists():
            dst.unlink()
        rel = os.path.relpath(str(src), start=str(project_root))
        dst.symlink_to(rel)
        return {"installed": True, "mode": "symlink", "path": str(dst), "target": rel}
    except OSError:
        # Fallback: copy the file.
        try:
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            return {"installed": True, "mode": "copy", "path": str(dst), "target": str(src)}
        except Exception as e:
            raise MCPError("INTERNAL", f"Failed to install hydra.py: {e}") from None


def register_tools(server: FastMCP) -> None:
    server.add_tool(hydraInfo, name="hydraInfo", structured_output=False)
    server.add_tool(hydraSetProject, name="hydraSetProject", structured_output=False)
    server.add_tool(hydraInit, name="hydraInit", structured_output=False)
    server.add_tool(hydraRun, name="hydraRun", structured_output=False)


def hydraInfo() -> CallToolResult:
    """Return information about the Hydra implementation used by this MCP server."""
    try:
        hydra_path = _hydra_py_path()
        sha1 = hashlib.sha1(hydra_path.read_bytes()).hexdigest() if hydra_path.exists() else None
        payload = _tool_ok({"hydraPath": str(hydra_path), "sha1": sha1})
        return _tool_success(payload)
    except MCPError as e:
        return _tool_error(e)
    except Exception as e:
        return _tool_error(MCPError("INTERNAL", str(e)))


def hydraSetProject(projectRoot: str) -> CallToolResult:
    """Set (and validate) the active project root for subsequent tool calls."""
    try:
        root = _require_project_root(projectRoot)
        payload = _tool_ok({"projectRoot": str(root)})
        return _tool_success(payload)
    except MCPError as e:
        return _tool_error(e)
    except Exception as e:
        return _tool_error(MCPError("INTERNAL", str(e)))


def hydraInit(projectRoot: str, session: str | None = None, installHydraPy: bool = False) -> CallToolResult:
    """
    Initialize Hydra inside a git project.

    - Validates and sets `projectRoot`
    - Runs: `hydra init [--session <name>]`
    - Optionally installs `hydra.py` into the project root (symlink/copy)
    """
    try:
        root = _require_project_root(projectRoot)
        hydra = _load_hydra()

        install_result: dict[str, Any] | None = None
        if installHydraPy:
            install_result = _maybe_install_hydra_py(root, force=False)

        argv: list[str] = ["init"]
        if session:
            argv.extend(["--session", session])

        code, out, err = _capture_hydra_main(hydra, argv, cwd=root)
        payload = _tool_ok(
            {
                "projectRoot": str(root),
                "exitCode": code,
                "stdout": out.strip(),
                "stderr": err.strip(),
                "installedHydraPy": install_result,
            }
        )
        return _tool_success(payload)
    except MCPError as e:
        return _tool_error(e)
    except Exception as e:
        return _tool_error(MCPError("INTERNAL", str(e)))


def hydraRun(args: list[str], projectRoot: str | None = None) -> CallToolResult:
    """
    Run an arbitrary `hydra.py` CLI command inside a project.

    Example:
      args=["task","list"]
    """
    try:
        if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
            raise MCPError("INVALID_ARG", "args must be a list of strings", {"args": args})

        root = _require_project_root(projectRoot)
        hydra = _load_hydra()
        code, out, err = _capture_hydra_main(hydra, args, cwd=root)
        payload = _tool_ok(
            {
                "projectRoot": str(root),
                "exitCode": code,
                "stdout": out.strip(),
                "stderr": err.strip(),
            }
        )
        return _tool_success(payload)
    except MCPError as e:
        return _tool_error(e)
    except SystemExit as e:
        # Just in case hydra.py calls SystemExit.
        code = int(getattr(e, "code", 1) or 0)
        payload = _tool_ok({"exitCode": code, "stdout": "", "stderr": str(e)})
        return _tool_success(payload)
    except Exception as e:
        return _tool_error(MCPError("INTERNAL", str(e)))

