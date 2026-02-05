#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import glob as globlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pathlib import PurePosixPath


class HydraError(RuntimeError):
    pass


MctlError = HydraError

HYDRA_DIRNAME = ".hydra"
AGENTS_DIRNAME = ".agents"
TASKS_DIRNAME = "tasks"
LOCKS_DB_NAME = "locks.db"
CONFIG_NAME = "config.json"
DEFAULT_SHARED_DEPS = ["node_modules", "venv", ".venv", "target"]
ZELLIJ_LAYOUT_NAME = "layout.kdl"

# Default Zellij layout (KDL). This is a per-project file created under `.hydra/`.
ZELLIJ_LAYOUT_TEMPLATE = """// CodeHydra default Zellij layout
//
// Usage:
//   zellij --session <project> --layout .hydra/layout.kdl
//
// Notes:
// - Starts with a single `main` tab (for the Claude Lead).
// - Create agent tabs dynamically (eg. `zellij action new-tab -n codex-1`).

layout {
    default_tab_template {
        // Standard Zellij UI (tab bar + status bar)
        pane size=1 borderless=true {
            plugin location="zellij:tab-bar"
        }
        children
        pane size=2 borderless=true {
            plugin location="zellij:status-bar"
        }
    }

    tab name="main" focus=true {
        pane
    }
}
"""

# Guide file templates
CLAUDE_MD_TEMPLATE = """# Claude Lead 工作指南

## 角色定位
你是 **Claude Lead**：项目经理，负责理解需求、拆解任务、调度子 AI（Codex/Gemini），对最终交付负责。

## 工作环境
- **当前位置**：main 终端（项目根目录）
- **Tmux Session**：项目名称
- **子 AI 位置**：同一 session 的不同 window

## 核心职责
1. 需求理解：与用户沟通，明确目标和验收标准
2. 任务拆解：将复杂任务分解为可执行的子任务
3. Agent 调度：派遣 Codex（执行）和 Gemini（顾问）
4. 进度跟踪：监控子 AI 进度，及时调整计划
5. 质量把控：验证交付物，确保符合要求

## 完整操作手册
详细操作说明请参考：`CLAUDE_GUIDE.md`
"""

AGENT_MD_TEMPLATE = """# Codex Agent 工作指南

## 角色定位
你是 **Codex**：代码执行者，负责实现具体功能、修复 Bug、编写测试。

## 工作环境
- **当前位置**：Agent 工作区（`.agents/<agent-name>/<task-id>/`）
- **Git 分支**：`agent/<agent-name>/<task-id>`
- **文件权限**：只能修改任务 allow 列表中的文件

## 核心职责
1. 代码实现：根据需求编写高质量代码
2. Bug 修复：定位并修复问题
3. 测试编写：确保代码可测试
4. 文档更新：必要时更新相关文档

## 提交修改

**重要**：任务完成后，必须先提交所有修改，然后再通知 Claude Lead。

```bash
# 1. 查看修改状态
git status

# 2. 添加所有修改（包括代码和文档）
git add <修改的文件>

# 3. 提交修改
git commit -m "任务描述

详细说明修改内容

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

**提交内容应包括**：
- 所有代码修改
- 测试文件
- 文档（如实现说明、设计文档等）
- 配置文件修改

**为什么要提交**：
- 确保修改可以被 merge 到主分支
- 保留完整的修改历史
- 避免 Claude Lead 无法合并你的工作

## 完成通知

任务完成后通知 Claude Lead：

**方式1（推荐）**：直接使用 hydra.py（已通过软链接在当前目录）
```bash
python hydra.py agent notify "任务完成：<简要说明>"
```

**方式2（备用）**：使用环境变量
```bash
python $HYDRA_PROJECT_ROOT/hydra.py agent notify "任务完成：<简要说明>"
```

**何时通知**：
- 任务完成时
- 遇到阻塞问题需要帮助时
- 发现需求不明确需要澄清时
"""

GEMINI_MD_TEMPLATE = """# Gemini Agent 工作指南

## 角色定位
你是 **Gemini**：技术顾问，负责提供第二观点、长文总结、架构建议。

## 工作环境
- **当前位置**：Agent 工作区（`.agents/<agent-name>/<task-id>/`）
- **Git 分支**：`agent/<agent-name>/<task-id>`
- **工作模式**：研究、分析、建议

## 核心职责
1. 技术调研：研究技术方案，提供多个选项
2. 架构建议：评估架构设计，指出潜在问题
3. 长文总结：总结复杂文档，提取关键信息
4. 第二观点：对 Codex 的方案提供补充意见

## 提交修改

**重要**：研究完成后，必须先提交所有修改，然后再通知 Claude Lead。

```bash
# 1. 查看修改状态
git status

# 2. 添加所有修改（包括研究文档、分析报告等）
git add <修改的文件>

# 3. 提交修改
git commit -m "研究任务描述

详细说明研究内容和结论

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

**提交内容应包括**：
- 研究报告和分析文档
- 技术方案对比文档
- 架构设计建议
- 总结文档

**为什么要提交**：
- 确保研究成果可以被 merge 到主分支
- 保留完整的研究历史
- 避免 Claude Lead 无法合并你的工作

## 完成通知

研究完成后通知 Claude Lead：

**方式1（推荐）**：直接使用 hydra.py（已通过软链接在当前目录）
```bash
python hydra.py agent notify "研究完成：<简要结论>"
```

**方式2（备用）**：使用环境变量
```bash
python $HYDRA_PROJECT_ROOT/hydra.py agent notify "研究完成：<简要结论>"
```

**何时通知**：
- 研究完成时
- 发现关键问题需要立即讨论时
- 需要 Claude Lead 做决策时
"""


def _now_ts() -> int:
    return int(time.time())


def _run(
    argv: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    check: bool = True,
    capture: bool = True,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    kwargs = {
        "cwd": str(cwd) if cwd else None,
        "check": False,
        "text": True,
        "env": env,
    }
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    proc = subprocess.run(list(argv), **kwargs)  # nosec - CLI tool by design
    if check and proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        msg = f"Command failed ({proc.returncode}): {' '.join(argv)}"
        if stdout:
            msg += f"\nSTDOUT:\n{stdout}"
        if stderr:
            msg += f"\nSTDERR:\n{stderr}"
        raise HydraError(msg)
    return proc


def _git(root: Path, args: Sequence[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    return _run(["git", *args], cwd=root, capture=capture)


def _tmux(args: Sequence[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    return _run(["tmux", *args], capture=capture)


def _tmux_available() -> bool:
    return shutil.which("tmux") is not None


def _zellij_available() -> bool:
    # Temporarily disabled - prefer tmux for stability
    return False
    # return shutil.which("zellij") is not None


def _find_project_root(start: Optional[Path] = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    # Prefer the common git dir so this works inside linked worktrees.
    try:
        out = _run(["git", "rev-parse", "--git-common-dir"], cwd=cur, capture=True).stdout.strip()
        if out:
            common_dir = Path(out)
            if not common_dir.is_absolute():
                common_dir = (cur / common_dir).resolve()
            if common_dir.is_dir():
                root = common_dir.parent
                if (root / ".git").exists():
                    return root
    except HydraError:
        pass

    for candidate in (cur, *cur.parents):
        if (candidate / ".git").is_dir():
            return candidate
    raise HydraError("Not inside a git repository (could not find a .git directory).")


def _find_hydra_root_for_hooks() -> Path:
    explicit = os.environ.get("HYDRA_PROJECT_ROOT", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return p.resolve()
    return _find_project_root()


def _ensure_dirs(root: Path) -> Tuple[Path, Path, Path]:
    hydra_dir = root / HYDRA_DIRNAME
    agents_dir = root / AGENTS_DIRNAME
    tasks_dir = root / TASKS_DIRNAME
    hydra_dir.mkdir(parents=True, exist_ok=True)
    agents_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    return hydra_dir, agents_dir, tasks_dir


def _ensure_config(hydra_dir: Path) -> Path:
    cfg = hydra_dir / CONFIG_NAME
    if not cfg.exists():
        cfg.write_text(json.dumps({"created": _now_ts(), "version": "0.1.0"}, indent=2) + "\n", encoding="utf-8")
    return cfg


def _ensure_zellij_layout(hydra_dir: Path, *, quiet: bool = True) -> Path:
    layout_path = hydra_dir / ZELLIJ_LAYOUT_NAME
    if not layout_path.exists():
        layout_path.write_text(ZELLIJ_LAYOUT_TEMPLATE, encoding="utf-8")
        if not quiet:
            print(f"Created {layout_path}")
    return layout_path


def _ensure_tmux_session(root: Path, hydra_dir: Path, explicit_session: Optional[str] = None) -> None:
    """Ensure tmux session exists for the project."""
    if not _tmux_available():
        print("hydra warning: tmux not found; skipping tmux session creation", file=sys.stderr)
        _save_session_name(hydra_dir, explicit_session or root.name)
        return

    # If explicit session name provided, use it directly
    if explicit_session:
        result = subprocess.run(
            ["tmux", "has-session", "-t", explicit_session],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"Tmux session '{explicit_session}' already exists")
            _save_session_name(hydra_dir, explicit_session)
            return
        # Create the session with explicit name
        try:
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", explicit_session, "-c", str(root)],
                check=True,
                capture_output=True,
                text=True
            )
            print(f"Created tmux session '{explicit_session}'")
            _save_session_name(hydra_dir, explicit_session)
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to create tmux session: {e.stderr}")
        return

    base_name = root.name
    session_name = base_name
    suffix = 0

    while True:
        # Check if session exists
        result = subprocess.run(
            ["tmux", "has-session", "-t", session_name],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            # Session doesn't exist, create it
            break

        # Session exists, check if it's for this project
        cwd_result = subprocess.run(
            ["tmux", "display-message", "-t", f"{session_name}:0", "-p", "#{pane_current_path}"],
            capture_output=True,
            text=True
        )

        if cwd_result.returncode == 0:
            session_cwd = Path(cwd_result.stdout.strip())
            if session_cwd == root:
                print(f"Tmux session '{session_name}' already exists for this project")
                _save_session_name(hydra_dir, session_name)
                return

        # Different project, try next suffix
        suffix += 1
        session_name = f"{base_name}-{suffix}"

    # Create new session
    try:
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session_name, "-c", str(root)],
            check=True,
            capture_output=True,
            text=True
        )
        print(f"Created tmux session '{session_name}'")
        _save_session_name(hydra_dir, session_name)
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to create tmux session: {e.stderr}")


def _ensure_zellij_session(root: Path, hydra_dir: Path) -> None:
    """Ensure Zellij session exists for the project."""
    if not _zellij_available():
        print("hydra warning: zellij not found; skipping zellij session creation", file=sys.stderr)
        _save_session_name(hydra_dir, root.name)
        return

    layout_path = hydra_dir / ZELLIJ_LAYOUT_NAME
    if not layout_path.exists():
        print(f"hydra warning: layout file {layout_path} not found", file=sys.stderr)
        _save_session_name(hydra_dir, root.name)
        return

    session_name = root.name

    # Check if session exists by listing sessions
    try:
        result = subprocess.run(
            ["zellij", "list-sessions"],
            capture_output=True,
            text=True,
            check=False
        )

        # Parse session list to check if our session exists
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                # Session line format: "session-name [Created ...] (current/EXITED)"
                if line.strip().startswith(session_name + " "):
                    print(f"Zellij session '{session_name}' already exists for this project")
                    _save_session_name(hydra_dir, session_name)
                    return
    except subprocess.CalledProcessError:
        pass

    # Session doesn't exist, create it in detached mode
    # Note: Zellij doesn't have a direct "detached" mode like tmux
    # We create the session but it will need to be attached manually
    print(f"Zellij session '{session_name}' needs to be created manually.")
    print(f"Run: zellij --new-session-with-layout {layout_path} -s {session_name}")
    _save_session_name(hydra_dir, session_name)


def _save_session_name(hydra_dir: Path, session_name: str) -> None:
    """Save tmux session name to config file."""
    cfg_path = hydra_dir / CONFIG_NAME
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    else:
        cfg = {}
    cfg["tmux_session"] = session_name
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _spawn_agent_zellij(session_name: str, tab_name: str, worktree: Path, cmd: List[str]) -> None:
    """Spawn an agent in a new Zellij tab."""
    # Create new tab
    subprocess.run(
        ["zellij", "action", "new-tab", "-n", tab_name],
        check=True,
        capture_output=True,
        text=True
    )

    # Switch to the new tab
    subprocess.run(
        ["zellij", "action", "go-to-tab-name", tab_name],
        check=True,
        capture_output=True,
        text=True
    )

    # Change to worktree directory
    cd_cmd = f"cd {worktree}"
    subprocess.run(
        ["zellij", "action", "write-chars", cd_cmd],
        check=True,
        capture_output=True,
        text=True
    )
    subprocess.run(
        ["zellij", "action", "write", "10"],  # Send Enter (ASCII 10)
        check=True,
        capture_output=True,
        text=True
    )

    # Send agent command
    agent_cmd = " ".join(cmd)
    subprocess.run(
        ["zellij", "action", "write-chars", agent_cmd],
        check=True,
        capture_output=True,
        text=True
    )
    subprocess.run(
        ["zellij", "action", "write", "10"],  # Send Enter
        check=True,
        capture_output=True,
        text=True
    )

    # Wait 0.5 second before switching back
    time.sleep(0.5)

    # Switch back to main tab
    subprocess.run(
        ["zellij", "action", "go-to-tab-name", "main"],
        check=True,
        capture_output=True,
        text=True
    )


def _connect_db(hydra_dir: Path) -> sqlite3.Connection:
    db_path = hydra_dir / LOCKS_DB_NAME
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS locks (
          file TEXT PRIMARY KEY,
          agent TEXT NOT NULL,
          task TEXT NOT NULL,
          locked_at INTEGER NOT NULL,
          tmux_session TEXT
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS locks_agent_task_idx ON locks(agent, task);")
    conn.commit()
    return conn


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | 0o111)


def _install_git_hooks(root: Path) -> None:
    hooks_dir = root / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    hook_header = "# Installed by CodeHydra (hydra.py)\n"
    # Record the actual path to hydra.py at install time
    hydra_py_path = Path(__file__).resolve()

    def hook_script(hook_name: str, args: str) -> str:
        return (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"{hook_header}"
            "\n"
            'PY="python3"\n'
            'command -v "$PY" >/dev/null 2>&1 || PY="python"\n'
            "\n"
            f'HYDRA_PY="{hydra_py_path}"\n'
            "\n"
            f'exec "$PY" "$HYDRA_PY" hook {hook_name} {args}\n'
        )

    scripts: Dict[str, str] = {
        "commit-msg": hook_script("commit-msg", '"$1"'),
        "pre-commit": hook_script("pre-commit", ""),
        "post-commit": hook_script("post-commit", ""),
    }

    ts = _now_ts()
    for name, content in scripts.items():
        path = hooks_dir / name
        if path.exists():
            try:
                existing = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                existing = ""
            if "Installed by CodeHydra" not in existing:
                backup = hooks_dir / f"{name}.bak.{ts}"
                path.rename(backup)
        _write_executable(path, content)

    _git(root, ["config", "core.hooksPath", str(hooks_dir.resolve())], capture=True)


def _sanitize_ref_component(value: str, *, label: str) -> str:
    if not value:
        raise MctlError(f"{label} must be non-empty.")
    if "/" in value or value.startswith(".") or value.endswith("."):
        raise MctlError(f"Invalid {label}: {value!r}")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    if not safe:
        raise MctlError(f"Invalid {label}: {value!r}")
    return safe


def _sanitize_task_id(task_id: str) -> str:
    # 支持两种格式：t1737123456（时间戳）或 t3005（短编号）
    if not re.fullmatch(r"t[0-9]+", task_id):
        raise MctlError(f"Invalid task id: {task_id!r} (expected like t1737123456 or t3005)")
    return task_id


def _is_glob_pattern(pattern: str) -> bool:
    if "**" in pattern:
        return True
    return any(ch in pattern for ch in "*?[]")


def _validate_allow_pattern(pattern: str) -> str:
    if not pattern:
        raise MctlError("Empty allow pattern is not allowed.")
    if os.path.isabs(pattern):
        raise MctlError(f"Allow pattern must be relative: {pattern!r}")
    norm = pattern.replace("\\", "/")
    if norm.startswith("../") or "/../" in norm or norm == "..":
        raise MctlError(f"Allow pattern must not escape repo root: {pattern!r}")
    return norm.lstrip("./")


def _expand_allow(root: Path, allow: Sequence[str]) -> List[str]:
    locked: set[str] = set()
    for raw in allow:
        pattern = _validate_allow_pattern(raw)
        if not _is_glob_pattern(pattern):
            # Lock explicit file paths even if they don't exist yet.
            locked.add(Path(pattern).as_posix())
            continue

        matches = globlib.glob(str(root / pattern), recursive=True)
        for m in matches:
            p = Path(m)
            try:
                rp = p.resolve()
            except FileNotFoundError:
                continue
            if not rp.is_file():
                continue
            try:
                rel = rp.relative_to(root)
            except ValueError:
                continue
            locked.add(rel.as_posix())
    return sorted(locked)


def _path_is_allowed(path: str, allow_patterns: Sequence[str]) -> bool:
    normalized_path = path.replace("\\", "/")
    for raw in allow_patterns:
        pattern = _validate_allow_pattern(raw)
        if fnmatch.fnmatch(normalized_path, pattern):
            return True
    return False


def _git_status_porcelain(worktree: Path) -> List[Tuple[str, str]]:
    out = _run(["git", "status", "--porcelain"], cwd=worktree, capture=True).stdout
    rows: List[Tuple[str, str]] = []
    for line in (out or "").splitlines():
        if not line:
            continue
        status = line[:2]
        rest = line[3:] if len(line) > 3 else ""
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        rows.append((status, rest.strip()))
    return rows


def _wait_for_worktree_quiet(
    worktree: Path, *, debounce_seconds: float, max_wait_seconds: float, poll_seconds: float = 0.5
) -> None:
    if debounce_seconds <= 0:
        return
    start = time.time()
    while True:
        rows = _git_status_porcelain(worktree)
        if not rows:
            return

        latest_mtime = 0.0
        for _status, rel in rows:
            if not rel:
                continue
            p = (worktree / rel).resolve()
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            if not p.is_file():
                continue
            latest_mtime = max(latest_mtime, st.st_mtime)

        quiet_for = time.time() - latest_mtime if latest_mtime else debounce_seconds
        if quiet_for >= debounce_seconds:
            return
        if (time.time() - start) >= max_wait_seconds:
            raise HydraError(
                f"Timed out waiting for files to stop changing (debounce={debounce_seconds}s, max_wait={max_wait_seconds}s)."
            )
        time.sleep(min(poll_seconds, max(0.05, debounce_seconds - quiet_for)))


def _git_staged_paths() -> List[str]:
    out = _run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRD"], capture=True).stdout
    return [line.strip() for line in (out or "").splitlines() if line.strip()]


def _hook_commit_msg(args: argparse.Namespace) -> int:
    msg_path = Path(args.msg_file)
    agent = os.environ.get("AGENT_ID", "").strip()
    task = os.environ.get("TASK_ID", "").strip()
    if not agent or not task:
        return 0
    try:
        text = msg_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 0

    if re.search(r"(?mi)^Agent:\\s*\\S+", text) and re.search(r"(?mi)^Task:\\s*\\S+", text):
        return 0

    out = text
    if out and not out.endswith("\n"):
        out += "\n"
    if out and not out.endswith("\n\n"):
        out += "\n"
    out += f"Agent: {agent}\nTask: {task}\n"
    msg_path.write_text(out, encoding="utf-8")
    return 0


def _hook_pre_commit(_args: argparse.Namespace) -> int:
    # Skip if explicitly requested (e.g., during merge)
    if os.environ.get("HYDRA_SKIP_HOOKS", "").strip():
        return 0

    agent = os.environ.get("AGENT_ID", "").strip()
    task_id = os.environ.get("TASK_ID", "").strip()
    if not agent or not task_id:
        return 0

    root = _find_hydra_root_for_hooks()
    hydra_dir, _agents_dir, tasks_dir = _ensure_dirs(root)
    task_file = os.environ.get("HYDRA_TASK_FILE", "").strip()
    if task_file:
        task_path = Path(task_file)
        if not task_path.is_absolute():
            task_path = (root / task_path).resolve()
        if not task_path.exists():
            raise HydraError(f"Task file not found: {task_path}")
        data = json.loads(task_path.read_text(encoding="utf-8"))
        allow = data.get("allow")
        if not isinstance(allow, list) or not all(isinstance(x, str) for x in allow):
            raise HydraError(f"Invalid task allow list in {task_path}")
        allow_patterns = [_validate_allow_pattern(x) for x in allow]
    else:
        task = _load_task(tasks_dir, task_id)
        allow_patterns = task.allow

    staged = _git_staged_paths()
    if not staged:
        return 0

    not_allowed = [p for p in staged if not _path_is_allowed(p, allow_patterns)]
    if not_allowed:
        pretty = "\n".join([f"- {p}" for p in not_allowed[:50]])
        more = "" if len(not_allowed) <= 50 else f"\n... and {len(not_allowed) - 50} more"
        raise HydraError(f"Pre-commit blocked: staged files outside task allow list:\n{pretty}{more}")

    db_path = hydra_dir / LOCKS_DB_NAME
    if not db_path.exists():
        raise HydraError(f"Locks DB not found: {db_path}. Did you run `hydra init`?")

    now = _now_ts()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("BEGIN IMMEDIATE;")
        try:
            conflicts: List[Tuple[str, str, str]] = []
            for rel in staged:
                row = conn.execute("SELECT agent, task FROM locks WHERE file=?", (rel,)).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO locks(file, agent, task, locked_at, tmux_session) VALUES(?,?,?,?,?)",
                        (rel, agent, task_id, now, ""),
                    )
                    continue
                locked_agent, locked_task = str(row[0]), str(row[1])
                if locked_agent != agent or locked_task != task_id:
                    conflicts.append((rel, locked_agent, locked_task))
            if conflicts:
                pretty = "\n".join([f"- {f} (held by {a}/{t})" for (f, a, t) in conflicts[:50]])
                more = "" if len(conflicts) <= 50 else f"\n... and {len(conflicts) - 50} more"
                raise HydraError(f"Pre-commit blocked: lock conflict(s):\n{pretty}{more}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return 0


def _append_journal_jsonl(path: Path, obj: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as f:
        try:
            import fcntl  # type: ignore

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        f.write(line)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
        try:
            import fcntl  # type: ignore

            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass


@dataclass(frozen=True)
class JournalEntry:
    ts: int
    sha: str
    agent: str
    task: str
    files: str
    index: int


def _format_ts_local(ts: int) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts)))
    except Exception:
        return str(ts)


def _parse_duration_seconds(text: str) -> Optional[int]:
    s = text.strip().lower()
    if not s:
        return None
    if s.endswith("ago"):
        s = s[: -len("ago")].strip()
    units = {
        "s": 1,
        "sec": 1,
        "secs": 1,
        "second": 1,
        "seconds": 1,
        "m": 60,
        "min": 60,
        "mins": 60,
        "minute": 60,
        "minutes": 60,
        "h": 3600,
        "hr": 3600,
        "hrs": 3600,
        "hour": 3600,
        "hours": 3600,
        "d": 86400,
        "day": 86400,
        "days": 86400,
        "w": 604800,
        "week": 604800,
        "weeks": 604800,
    }
    total = 0.0
    pattern = re.compile(r"(\d+(?:\.\d+)?)\s*([a-z]+)")
    pos = 0
    for m in pattern.finditer(s):
        if s[pos : m.start()].strip():
            return None
        pos = m.end()
        num = float(m.group(1))
        unit = m.group(2)
        mult = units.get(unit)
        if mult is None:
            return None
        total += num * mult
    if s[pos:].strip():
        return None
    return int(total)


def _parse_datetime_local_ts(text: str) -> Optional[int]:
    s = text.strip()
    if not s:
        return None
    s = s.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            st = time.strptime(s, fmt)
        except ValueError:
            continue
        try:
            return int(time.mktime(st))
        except Exception:
            return None
    return None


def _parse_since_to_ts(value: str, *, now_ts: Optional[int] = None) -> int:
    s = (value or "").strip()
    if not s:
        raise HydraError("Empty --since value.")
    if re.fullmatch(r"\d+", s):
        return int(s)
    now = _now_ts() if now_ts is None else int(now_ts)
    delta = _parse_duration_seconds(s)
    if delta is not None:
        return now - delta
    dt = _parse_datetime_local_ts(s)
    if dt is not None:
        return dt
    raise HydraError(
        f"Unable to parse --since: {value!r}. Expected unix seconds, 'YYYY-MM-DD[ HH:MM[:SS]]', or duration like '10 minutes'."
    )


def _read_journal_entries(path: Path) -> Tuple[List[JournalEntry], int]:
    if not path.exists():
        return [], 0
    entries: List[JournalEntry] = []
    invalid = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for idx, raw in enumerate(f):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1
                continue
            if not isinstance(obj, dict):
                invalid += 1
                continue
            try:
                ts = int(obj.get("ts") or 0)
                sha = str(obj.get("sha") or "")
                agent = str(obj.get("agent") or "")
                task = str(obj.get("task") or "")
                files = str(obj.get("files") or "")
            except Exception:
                invalid += 1
                continue
            entries.append(JournalEntry(ts=ts, sha=sha, agent=agent, task=task, files=files, index=idx))
    return entries, invalid


def _format_journal_files(files: str) -> str:
    parts: List[str] = []
    for raw in (files or "").split(";"):
        raw = raw.strip()
        if not raw:
            continue
        cols = [c for c in raw.split("\t") if c != ""]
        status = cols[0].strip() if cols else ""
        paths = [c.strip() for c in cols[1:] if c.strip()]
        if not status:
            continue
        if status.startswith(("R", "C")) and len(paths) >= 2:
            parts.append(f"{status} {paths[0]} -> {paths[1]}")
        elif paths:
            if len(paths) == 1:
                parts.append(f"{status} {paths[0]}")
            else:
                parts.append(f"{status} {' '.join(paths)}")
        else:
            parts.append(status)
    return "; ".join(parts)


def _hook_post_commit(_args: argparse.Namespace) -> int:
    root = _find_hydra_root_for_hooks()
    hydra_dir, _agents_dir, _tasks_dir = _ensure_dirs(root)

    sha = _run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    files_out = _run(["git", "diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD"], capture=True).stdout
    files = ";".join([line.strip() for line in (files_out or "").splitlines() if line.strip()])

    agent = os.environ.get("AGENT_ID", "").strip()
    task = os.environ.get("TASK_ID", "").strip()
    entry = {"ts": _now_ts(), "sha": sha, "agent": agent, "task": task, "files": files}
    _append_journal_jsonl(hydra_dir / "journal.jsonl", entry)
    return 0


def cmd_hook(args: argparse.Namespace) -> int:
    if args.hook_cmd == "commit-msg":
        return _hook_commit_msg(args)
    if args.hook_cmd == "pre-commit":
        return _hook_pre_commit(args)
    if args.hook_cmd == "post-commit":
        return _hook_post_commit(args)
    raise HydraError(f"Unknown hook command: {args.hook_cmd}")


def _tmux_session_exists(session: str) -> bool:
    if not _tmux_available():
        return False
    try:
        proc = subprocess.run(  # nosec - CLI tool by design
            ["tmux", "has-session", "-t", session],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False
    return proc.returncode == 0


def _cleanup_dead_locks(conn: sqlite3.Connection) -> int:
    if not _tmux_available():
        return 0
    rows = conn.execute(
        "SELECT DISTINCT tmux_session FROM locks WHERE tmux_session IS NOT NULL AND tmux_session != ''"
    ).fetchall()
    released = 0
    for (session,) in rows:
        if not session:
            continue
        if _tmux_session_exists(session):
            continue
        released += conn.execute("DELETE FROM locks WHERE tmux_session=?", (session,)).rowcount
    return released


def _acquire_locks(
    conn: sqlite3.Connection,
    *,
    files: Sequence[str],
    agent: str,
    task: str,
    tmux_session: Optional[str],
) -> None:
    unique = sorted(set(files))
    now = _now_ts()
    conn.execute("BEGIN IMMEDIATE;")
    try:
        _cleanup_dead_locks(conn)
        if unique:
            placeholders = ",".join("?" for _ in unique)
            rows = conn.execute(
                f"SELECT file, agent, task FROM locks WHERE file IN ({placeholders})",
                tuple(unique),
            ).fetchall()
            conflicts = [(f, a, t) for (f, a, t) in rows if (a != agent or t != task)]
            if conflicts:
                pretty = "\n".join([f"- {f} (held by {a} / {t})" for (f, a, t) in conflicts[:20]])
                more = "" if len(conflicts) <= 20 else f"\n... and {len(conflicts) - 20} more"
                raise MctlError(f"Lock conflict for agent={agent} task={task}:\n{pretty}{more}")

            for f in unique:
                try:
                    conn.execute(
                        "INSERT INTO locks(file, agent, task, locked_at, tmux_session) VALUES(?,?,?,?,?)",
                        (f, agent, task, now, tmux_session),
                    )
                except sqlite3.IntegrityError:
                    conn.execute(
                        "UPDATE locks SET agent=?, task=?, locked_at=?, tmux_session=? WHERE file=?",
                        (agent, task, now, tmux_session, f),
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _set_locks_tmux_session(conn: sqlite3.Connection, *, agent: str, task: str, tmux_session: str) -> int:
    conn.execute("BEGIN IMMEDIATE;")
    try:
        updated = conn.execute(
            "UPDATE locks SET tmux_session=? WHERE agent=? AND task=?",
            (tmux_session, agent, task),
        ).rowcount
        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        raise


def _release_locks(conn: sqlite3.Connection, *, agent: str, task: str) -> int:
    conn.execute("BEGIN IMMEDIATE;")
    try:
        released = conn.execute("DELETE FROM locks WHERE agent=? AND task=?", (agent, task)).rowcount
        conn.commit()
        return released
    except Exception:
        conn.rollback()
        raise


def _list_locks(conn: sqlite3.Connection) -> List[Tuple[str, str, str, int, str]]:
    rows = conn.execute(
        "SELECT file, agent, task, locked_at, COALESCE(tmux_session, '') FROM locks ORDER BY file"
    ).fetchall()
    return [(str(f), str(a), str(t), int(ts), str(s)) for (f, a, t, ts, s) in rows]


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    allow: List[str]
    created: int


def _task_path(tasks_dir: Path, task_id: str) -> Path:
    return tasks_dir / f"{task_id}.json"


def _load_task(tasks_dir: Path, task_id: str) -> Task:
    task_id = _sanitize_task_id(task_id)
    path = _task_path(tasks_dir, task_id)
    if not path.exists():
        raise MctlError(f"Task not found: {task_id} ({path})")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("id") != task_id:
        raise MctlError(f"Task file id mismatch: expected {task_id}, got {data.get('id')!r}")
    allow = data.get("allow")
    if not isinstance(allow, list) or not all(isinstance(x, str) for x in allow):
        raise MctlError(f"Invalid task allow list in {path}")
    return Task(
        id=task_id,
        title=str(data.get("title", "")),
        allow=[_validate_allow_pattern(x) for x in allow],
        created=int(data.get("created") or 0),
    )


def _create_task(tasks_dir: Path, *, title: str, allow: Sequence[str], explicit_id: Optional[str]) -> Task:
    if not allow:
        raise MctlError("At least one --allow pattern is required.")
    created = _now_ts()
    if explicit_id:
        task_id = _sanitize_task_id(explicit_id)
    else:
        base = f"t{created}"
        task_id = base
        for i in range(0, 1000):
            path = _task_path(tasks_dir, task_id)
            if not path.exists():
                break
            task_id = f"{base}{i + 1:02d}"
        else:
            raise MctlError(f"Unable to allocate unique task id for base {base}")

    path = _task_path(tasks_dir, task_id)
    if path.exists():
        raise MctlError(f"Task already exists: {task_id} ({path})")

    task = {
        "id": task_id,
        "title": title,
        "allow": [_validate_allow_pattern(x) for x in allow],
        "created": created,
    }
    path.write_text(json.dumps(task, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return Task(id=task_id, title=title, allow=list(task["allow"]), created=created)


def _default_base_ref(root: Path) -> str:
    for candidate in ("main", "master"):
        proc = subprocess.run(  # nosec - CLI tool by design
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"],
            cwd=str(root),
        )
        if proc.returncode == 0:
            return candidate
    return _git(root, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip() or "HEAD"


def _create_worktree(
    root: Path,
    *,
    worktree: Path,
    branch: str,
    base_ref: str,
    dry_run: bool,
) -> None:
    if worktree.exists():
        raise MctlError(f"Worktree path already exists: {worktree}")
    worktree.parent.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(  # nosec - CLI tool by design
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=str(root),
    )
    if proc.returncode == 0:
        raise MctlError(f"Branch already exists: {branch}")

    cmd = ["git", "worktree", "add", "-b", branch, str(worktree), base_ref]
    if dry_run:
        print("[dry-run]", " ".join(cmd))
        return
    _run(cmd, cwd=root, capture=True)


def _relative_symlink(target: Path, dest: Path, *, dry_run: bool) -> None:
    rel = os.path.relpath(str(target), str(dest.parent))
    if dry_run:
        print(f"[dry-run] ln -s {rel} {dest}")
        return
    dest.symlink_to(rel)


def _share_deps(root: Path, worktree: Path, deps: Sequence[str], *, dry_run: bool) -> List[str]:
    shared: List[str] = []
    for d in deps:
        src = root / d
        if not src.exists():
            continue
        dest = worktree / d
        if dest.exists() or dest.is_symlink():
            if dest.is_symlink():
                try:
                    if dest.resolve() == src.resolve():
                        shared.append(d)
                        continue
                except FileNotFoundError:
                    pass
            continue
        _relative_symlink(src, dest, dry_run=dry_run)
        shared.append(d)
    return shared


def _tmux_session_name(agent: str, task: str) -> str:
    # tmux session names can't contain ':'; keep it simple and stable.
    a = re.sub(r"[^A-Za-z0-9._-]+", "-", agent).strip("-")
    t = re.sub(r"[^A-Za-z0-9._-]+", "-", task).strip("-")
    name = f"hydra-{a}-{t}"
    return name[:60]  # tmux has practical limits; keep it short


def _start_tmux_window(
    *,
    project_session: str,
    window_name: str,
    worktree: Path,
    env_vars: Dict[str, str],
    shell: str,
    dry_run: bool,
) -> None:
    """Create a new window in the project's tmux session."""
    # Check if window already exists
    result = subprocess.run(
        ["tmux", "list-windows", "-t", project_session, "-F", "#{window_name}"],
        capture_output=True,
        text=True,
    )
    existing_windows = result.stdout.strip().split("\n") if result.stdout.strip() else []
    if window_name in existing_windows:
        raise MctlError(f"tmux window already exists: {window_name} in session {project_session}")

    if dry_run:
        print(f"[dry-run] tmux new-window -t {project_session} -n {window_name} -c {worktree}")
        return
    
    # Create window with shell
    subprocess.run(
        ["tmux", "new-window", "-t", project_session, "-n", window_name, "-c", str(worktree)],
        check=True,
        capture_output=True,
        text=True,
    )
    
    # Set environment variables in the new window
    for k, v in env_vars.items():
        subprocess.run(
            ["tmux", "send-keys", "-t", f"{project_session}:{window_name}", f"export {k}={v}", "Enter"],
            check=False,
            capture_output=True,
        )


def cmd_init(args: argparse.Namespace) -> int:
    root = _find_project_root()
    hydra_dir, _agents_dir, _tasks_dir = _ensure_dirs(root)
    _ensure_config(hydra_dir)
    _ensure_zellij_layout(hydra_dir, quiet=False)
    with _connect_db(hydra_dir) as conn:
        _cleanup_dead_locks(conn)
    # Hooks disabled - they add complexity without much benefit
    # _install_git_hooks(root)
    _ensure_tmux_session(root, hydra_dir, getattr(args, 'session', None))

    # Create claude.md guide file
    claude_md = root / "claude.md"
    if not claude_md.exists():
        claude_md.write_text(CLAUDE_MD_TEMPLATE, encoding="utf-8")
        print(f"Created {claude_md}")

    print(f"Initialized hydra in {root}")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    root = _find_project_root()
    hydra_dir, agents_dir, tasks_dir = _ensure_dirs(root)
    _ensure_config(hydra_dir)

    agent = _sanitize_ref_component(args.agent, label="agent name")
    task_id: Optional[str] = args.task
    if task_id:
        task_id = _sanitize_task_id(task_id)
        worktree = agents_dir / agent / task_id
        if not worktree.exists():
            raise HydraError(f"Worktree not found: {worktree}")
    else:
        agent_dir = agents_dir / agent
        if not agent_dir.exists():
            raise HydraError(f"Agent directory not found: {agent_dir}")
        candidates = sorted([p.name for p in agent_dir.iterdir() if p.is_dir() and re.fullmatch(r"t[0-9]{6,}", p.name)])
        if not candidates:
            raise HydraError(f"No tasks found under {agent_dir} (expected directories like t1737123456)")
        if len(candidates) != 1:
            raise HydraError(f"Multiple tasks found for {agent}; please specify --task. Found: {', '.join(candidates)}")
        task_id = candidates[0]
        worktree = agent_dir / task_id

    task = _load_task(tasks_dir, task_id)

    rows = _git_status_porcelain(worktree)
    if not rows:
        print("No changes")
        return 0

    _wait_for_worktree_quiet(
        worktree, debounce_seconds=float(args.debounce), max_wait_seconds=float(args.max_wait), poll_seconds=0.5
    )

    _run(["git", "add", "-A"], cwd=worktree, capture=True)
    if not _git_status_porcelain(worktree):
        print("No changes")
        return 0

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_now_ts()))
    msg = f"Snapshot: {timestamp}"

    env = os.environ.copy()
    env.update(
        {
            "AGENT_ID": agent,
            "TASK_ID": task.id,
            "HYDRA_PROJECT_ROOT": str(root),
            "HYDRA_TASK_FILE": str(_task_path(tasks_dir, task.id)),
            "GIT_AUTHOR_NAME": f"{agent} Agent",
            "GIT_AUTHOR_EMAIL": f"{agent}@agents.local",
            "GIT_COMMITTER_NAME": f"{agent} Agent",
            "GIT_COMMITTER_EMAIL": f"{agent}@agents.local",
        }
    )
    _run(["git", "commit", "-m", msg], cwd=worktree, capture=True, env=env)
    sha = _run(["git", "rev-parse", "HEAD"], cwd=worktree, capture=True, env=env).stdout.strip()
    print(sha)
    return 0


def cmd_changes(args: argparse.Namespace) -> int:
    root = _find_project_root()
    hydra_dir, _agents_dir, _tasks_dir = _ensure_dirs(root)
    _ensure_config(hydra_dir)

    since_ts: Optional[int] = None
    if args.since:
        since_ts = _parse_since_to_ts(args.since, now_ts=_now_ts())

    agent_filter: Optional[str] = None
    if args.agent:
        agent_filter = _sanitize_ref_component(args.agent, label="agent")

    task_filter: Optional[str] = None
    if args.task:
        task_filter = _sanitize_task_id(args.task)

    journal_path = hydra_dir / "journal.jsonl"
    entries, invalid = _read_journal_entries(journal_path)
    if invalid:
        print(f"hydra warning: skipped {invalid} invalid journal line(s) in {journal_path}", file=sys.stderr)

    filtered: List[JournalEntry] = []
    for e in entries:
        if since_ts is not None and int(e.ts) < since_ts:
            continue
        if agent_filter is not None and e.agent != agent_filter:
            continue
        if task_filter is not None and e.task != task_filter:
            continue
        filtered.append(e)

    filtered.sort(key=lambda x: (int(x.ts), int(x.index)))
    if not filtered:
        return 0

    for e in filtered:
        ts = _format_ts_local(e.ts)
        agent = e.agent or "-"
        task = e.task or "-"
        files = _format_journal_files(e.files)
        print(f"{ts}\t{agent}\t{task}\t{e.sha}\t{files}")
    return 0


def _git_ref_exists(root: Path, ref: str) -> bool:
    proc = subprocess.run(  # nosec - CLI tool by design
        ["git", "show-ref", "--verify", "--quiet", ref],
        cwd=str(root),
    )
    return proc.returncode == 0


@dataclass(frozen=True)
class GitWorktree:
    path: Path
    branch_ref: str


def _list_git_worktrees(root: Path) -> List[GitWorktree]:
    out = _run(["git", "worktree", "list", "--porcelain"], cwd=root, capture=True).stdout
    items: List[GitWorktree] = []
    cur_path: Optional[Path] = None
    cur_branch = ""
    for raw in (out or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("worktree "):
            if cur_path is not None:
                items.append(GitWorktree(path=cur_path, branch_ref=cur_branch))
            cur_path = Path(line.split(" ", 1)[1]).expanduser().resolve()
            cur_branch = ""
            continue
        if line.startswith("branch "):
            cur_branch = line.split(" ", 1)[1].strip()
            continue
    if cur_path is not None:
        items.append(GitWorktree(path=cur_path, branch_ref=cur_branch))
    return items


def _find_worktree_by_branch(root: Path, branch_ref: str) -> Optional[Path]:
    for wt in _list_git_worktrees(root):
        if wt.branch_ref == branch_ref:
            return wt.path
    return None


def _default_trunk_ref(root: Path) -> str:
    for candidate in ("main", "master"):
        if _git_ref_exists(root, f"refs/heads/{candidate}"):
            return candidate
    raise HydraError("No trunk branch found (expected refs/heads/main or refs/heads/master).")


def _ensure_worktree_clean(
    worktree: Path,
    *,
    label: str,
    allow_untracked: bool,
) -> None:
    out = _run(["git", "status", "--porcelain"], cwd=worktree, capture=True).stdout
    lines = [line.rstrip("\n") for line in (out or "").splitlines() if line.strip()]
    if allow_untracked:
        lines = [line for line in lines if not line.startswith("??")]
    if not lines:
        return
    preview = "\n".join(lines[:20])
    more = "" if len(lines) <= 20 else f"\n... and {len(lines) - 20} more"
    raise HydraError(f"{label} has uncommitted changes in {worktree}:\n{preview}{more}")


def _abort_merge(worktree: Path) -> None:
    proc = _run(["git", "merge", "--abort"], cwd=worktree, capture=True, check=False)
    if proc.returncode == 0:
        return
    _run(["git", "reset", "--hard", "HEAD"], cwd=worktree, capture=True, check=False)


def _abort_revert(worktree: Path) -> None:
    proc = _run(["git", "revert", "--abort"], cwd=worktree, capture=True, check=False)
    if proc.returncode == 0:
        return
    _run(["git", "reset", "--hard", "HEAD"], cwd=worktree, capture=True, check=False)


def _resolve_agent_task(
    *,
    root: Path,
    hydra_dir: Path,
    agents_dir: Path,
    agent: str,
    task_opt: Optional[str],
) -> str:
    if task_opt:
        return _sanitize_task_id(task_opt)

    tasks = _list_agent_tasks_from_branches(root, agent)
    if not tasks:
        agent_dir = agents_dir / agent
        if agent_dir.exists():
            tasks = sorted(
                [p.name for p in agent_dir.iterdir() if p.is_dir() and re.fullmatch(r"t[0-9]{6,}", p.name)]
            )
    if not tasks:
        entries, _invalid = _read_journal_entries(hydra_dir / "journal.jsonl")
        tasks = sorted({e.task for e in entries if e.agent == agent and e.task})

    if not tasks:
        raise HydraError(f"No tasks found for agent {agent!r}.")
    if len(tasks) != 1:
        raise HydraError(f"Multiple tasks found for {agent}; please specify --task. Found: {', '.join(tasks)}")
    return tasks[0]


def _rewrite_headish_for_branch(ref: str, *, branch: str) -> str:
    s = (ref or "").strip()
    if s == "HEAD":
        return branch
    if s.startswith("HEAD") and len(s) > 4 and s[4] in "^~":
        return f"{branch}{s[4:]}"
    return s


def _resolve_commit(root: Path, ref: str) -> str:
    sha = _run(["git", "rev-parse", "--verify", ref], cwd=root, capture=True).stdout.strip()
    if not sha:
        raise HydraError(f"Unable to resolve ref: {ref!r}")
    return sha


def _list_changed_files(root: Path, *, base_ref: str, target_ref: str) -> List[str]:
    merge_base = _run(["git", "merge-base", base_ref, target_ref], cwd=root, capture=True, check=True).stdout.strip()
    if not merge_base:
        raise HydraError(f"Unable to find merge-base between {base_ref!r} and {target_ref!r}.")
    out = _run(["git", "diff", "--name-only", f"{merge_base}..{target_ref}"], cwd=root, capture=True, check=True).stdout
    return [line.strip() for line in (out or "").splitlines() if line.strip()]


def _list_agent_tasks_from_branches(root: Path, agent: str) -> List[str]:
    out = _run(
        ["git", "for-each-ref", "--format=%(refname:short)", f"refs/heads/agent/{agent}/"],
        cwd=root,
        capture=True,
        check=True,
    ).stdout
    tasks: List[str] = []
    for line in (out or "").splitlines():
        ref = line.strip()
        if not ref:
            continue
        # agent/<agent>/<task>
        parts = ref.split("/", 2)
        if len(parts) != 3:
            continue
        task = parts[2]
        if re.fullmatch(r"t[0-9]{6,}", task):
            tasks.append(task)
    return sorted(set(tasks))


def cmd_diff(args: argparse.Namespace) -> int:
    root = _find_project_root()
    hydra_dir, agents_dir, _tasks_dir = _ensure_dirs(root)
    _ensure_config(hydra_dir)

    agent = _sanitize_ref_component(args.agent, label="agent name")
    task_filter: Optional[str] = _sanitize_task_id(args.task) if args.task else None

    tasks: List[str] = []
    if task_filter is not None:
        tasks = [task_filter]
    else:
        tasks = _list_agent_tasks_from_branches(root, agent)
        if not tasks:
            journal_entries, _invalid = _read_journal_entries(hydra_dir / "journal.jsonl")
            tasks = sorted({e.task for e in journal_entries if e.agent == agent and e.task})
        if not tasks:
            agent_dir = agents_dir / agent
            if agent_dir.exists():
                tasks = sorted(
                    [
                        p.name
                        for p in agent_dir.iterdir()
                        if p.is_dir() and re.fullmatch(r"t[0-9]{6,}", p.name)
                    ]
                )

    if not tasks:
        raise HydraError(f"No tasks found for agent {agent!r}.")

    journal_entries, _invalid = _read_journal_entries(hydra_dir / "journal.jsonl")
    last_by_task: Dict[str, Tuple[int, str]] = {}
    for e in journal_entries:
        if e.agent != agent or not e.task:
            continue
        if task_filter is not None and e.task != task_filter:
            continue
        prev = last_by_task.get(e.task)
        if prev is None or int(e.ts) >= int(prev[0]):
            last_by_task[e.task] = (int(e.ts), e.sha)

    base_ref = _default_base_ref(root)
    multi = len(tasks) > 1
    printed_any = False

    for task in tasks:
        branch = f"agent/{agent}/{task}"
        if _git_ref_exists(root, f"refs/heads/{branch}"):
            target_ref = branch
        else:
            last = last_by_task.get(task)
            if last is None or not last[1]:
                raise HydraError(f"Cannot find branch or journal commit for {agent}/{task}.")
            target_ref = last[1]

        merge_base = _run(["git", "merge-base", base_ref, target_ref], cwd=root, capture=True, check=True).stdout.strip()
        if not merge_base:
            raise HydraError(f"Unable to find merge-base between {base_ref!r} and {target_ref!r}.")

        if multi:
            print(f"=== diff {agent}/{task} ({base_ref}..{target_ref}) ===", file=sys.stderr)

        proc = _run(["git", "diff", f"{merge_base}..{target_ref}"], cwd=root, capture=True, check=True)
        out = proc.stdout or ""
        if out:
            sys.stdout.write(out)
            if not out.endswith("\n"):
                sys.stdout.write("\n")
            printed_any = True
        elif multi:
            print("(no diff)", file=sys.stderr)

    if not printed_any and not multi:
        # Single task and no diff; keep output explicit.
        print("No diff")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    root = _find_project_root()
    hydra_dir, agents_dir, tasks_dir = _ensure_dirs(root)
    _ensure_config(hydra_dir)

    agent = _sanitize_ref_component(args.agent, label="agent name")
    task_id = _resolve_agent_task(root=root, hydra_dir=hydra_dir, agents_dir=agents_dir, agent=agent, task_opt=args.task)
    _load_task(tasks_dir, task_id)
    branch = f"agent/{agent}/{task_id}"
    branch_ref = f"refs/heads/{branch}"
    
    trunk = _default_trunk_ref(root)
    trunk_ref = f"refs/heads/{trunk}"
    trunk_worktree = _find_worktree_by_branch(root, trunk_ref)
    
    # Handle --abort
    if args.abort:
        if trunk_worktree is None:
            raise HydraError(f"No trunk worktree found for {trunk}")
        _abort_merge(trunk_worktree)
        print(f"Merge aborted in {trunk_worktree}")
        return 0
    
    if not _git_ref_exists(root, branch_ref):
        raise HydraError(f"Agent branch not found: {branch_ref}")

    trunk = _default_trunk_ref(root)
    trunk_ref = f"refs/heads/{trunk}"

    trunk_worktree = _find_worktree_by_branch(root, trunk_ref)
    created_trunk_worktree = False
    if trunk_worktree is None:
        wt = hydra_dir / "worktrees" / f"trunk-{trunk}-{_now_ts()}"
        wt.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "worktree", "add", str(wt), trunk], cwd=root, capture=True, check=True)
        trunk_worktree = wt
        created_trunk_worktree = True

    try:
        head_branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=trunk_worktree, capture=True).stdout.strip()
        if head_branch != trunk:
            raise HydraError(f"Trunk worktree {trunk_worktree} is on {head_branch!r}, expected {trunk!r}.")
        _ensure_worktree_clean(trunk_worktree, label=f"Trunk worktree ({trunk})", allow_untracked=True)

        agent_worktree = _find_worktree_by_branch(root, branch_ref)
        if agent_worktree is None:
            candidate = agents_dir / agent / task_id
            if candidate.exists():
                agent_worktree = candidate
        if agent_worktree is not None and agent_worktree.exists():
            _ensure_worktree_clean(agent_worktree, label=f"Agent worktree ({agent}/{task_id})", allow_untracked=False)

        changed = _list_changed_files(root, base_ref=trunk, target_ref=branch)
        if changed:
            with _connect_db(hydra_dir) as conn:
                _cleanup_dead_locks(conn)
                conflicts: List[Tuple[str, str, str]] = []
                for rel in changed:
                    row = conn.execute("SELECT agent, task FROM locks WHERE file=?", (rel,)).fetchone()
                    if row is None:
                        continue
                    locked_agent, locked_task = str(row[0]), str(row[1])
                    if locked_agent != agent or locked_task != task_id:
                        conflicts.append((rel, locked_agent, locked_task))
                if conflicts:
                    pretty = "\n".join([f"- {f} (held by {a}/{t})" for (f, a, t) in conflicts[:50]])
                    more = "" if len(conflicts) <= 50 else f"\n... and {len(conflicts) - 50} more"
                    raise HydraError(f"Merge blocked: target files are locked by other agents:\n{pretty}{more}")

        env = os.environ.copy()
        env.update(
            {
                "AGENT_ID": agent,
                "TASK_ID": task_id,
                "HYDRA_PROJECT_ROOT": str(root),
                "HYDRA_TASK_FILE": str(_task_path(tasks_dir, task_id)),
                "GIT_AUTHOR_NAME": f"{agent} Agent",
                "GIT_AUTHOR_EMAIL": f"{agent}@agents.local",
                "GIT_COMMITTER_NAME": f"{agent} Agent",
                "GIT_COMMITTER_EMAIL": f"{agent}@agents.local",
            }
        )

        # Skip pre-commit hook during merge (we're merging agent work back to trunk)
        env["HYDRA_SKIP_HOOKS"] = "1"

        if args.squash:
            proc = _run(["git", "merge", "--squash", branch], cwd=trunk_worktree, capture=True, check=False, env=env)
            if proc.returncode != 0:
                # Check if it's a conflict (not other errors)
                status = _run(["git", "status", "--porcelain"], cwd=trunk_worktree, capture=True).stdout
                has_conflicts = any(line.startswith("UU ") or line.startswith("AA ") or line.startswith("DD ") for line in status.splitlines())
                
                if has_conflicts:
                    # Don't abort, let user resolve
                    conflict_files = [line.split()[-1] for line in status.splitlines() if line.startswith(("UU ", "AA ", "DD "))]
                    print(f"\n⚠️  Merge conflict while squash merging {branch!r} into {trunk!r}")
                    print(f"\nConflict files:")
                    for f in conflict_files:
                        print(f"  - {f}")
                    print(f"\nTo resolve:")
                    print(f"  1. cd {trunk_worktree}")
                    print(f"  2. Edit conflict files and resolve markers")
                    print(f"  3. git add <resolved-files>")
                    print(f"  4. git commit -m 'Merge {branch} into {trunk} (squash)'")
                    print(f"  5. Or run: hydra merge {agent} --task {task_id} --abort  (to abort)")
                    return 1  # Non-zero but don't abort
                else:
                    # Other error, abort
                    _abort_merge(trunk_worktree)
                    stderr = (proc.stderr or "").strip()
                    raise HydraError(
                        f"Merge failed (not a conflict): {branch!r} into {trunk!r} (merge aborted).\n{stderr}"
                    )
            staged = _run(["git", "diff", "--cached", "--name-only"], cwd=trunk_worktree, capture=True).stdout
            if staged.strip():
                msg = f"Merge {branch} into {trunk} (squash)"
                _run(["git", "commit", "-m", msg], cwd=trunk_worktree, capture=True, env=env)
        else:
            proc = _run(
                ["git", "merge", "--no-ff", "--no-edit", branch],
                cwd=trunk_worktree,
                capture=True,
                check=False,
                env=env,
            )
            if proc.returncode != 0:
                # Check if it's a conflict (not other errors)
                status = _run(["git", "status", "--porcelain"], cwd=trunk_worktree, capture=True).stdout
                has_conflicts = any(line.startswith("UU ") or line.startswith("AA ") or line.startswith("DD ") for line in status.splitlines())
                
                if has_conflicts:
                    # Don't abort, let user resolve
                    conflict_files = [line.split()[-1] for line in status.splitlines() if line.startswith(("UU ", "AA ", "DD "))]
                    print(f"\n⚠️  Merge conflict while merging {branch!r} into {trunk!r}")
                    print(f"\nConflict files:")
                    for f in conflict_files:
                        print(f"  - {f}")
                    print(f"\nTo resolve:")
                    print(f"  1. cd {trunk_worktree}")
                    print(f"  2. Edit conflict files and resolve markers")
                    print(f"  3. git add <resolved-files>")
                    print(f"  4. git commit --no-edit")
                    print(f"  5. Or run: hydra merge {agent} --task {task_id} --abort  (to abort)")
                    return 1  # Non-zero but don't abort
                else:
                    # Other error, abort
                    _abort_merge(trunk_worktree)
                    stderr = (proc.stderr or "").strip()
                    raise HydraError(
                        f"Merge failed (not a conflict): {branch!r} into {trunk!r} (merge aborted).\n{stderr}"
                    )

        merged_sha = _run(["git", "rev-parse", "HEAD"], cwd=trunk_worktree, capture=True).stdout.strip()

    finally:
        if created_trunk_worktree and trunk_worktree is not None:
            _run(["git", "worktree", "remove", "--force", str(trunk_worktree)], cwd=root, capture=True, check=False)

    session = _tmux_session_name(agent, task_id)
    if _tmux_session_exists(session):
        _tmux(["kill-session", "-t", session], capture=True)

    with _connect_db(hydra_dir) as conn:
        released = _release_locks(conn, agent=agent, task=task_id)
    print(f"hydra: released {released} lock(s) for {agent}/{task_id}", file=sys.stderr)

    agent_worktree = _find_worktree_by_branch(root, branch_ref)
    if agent_worktree is None:
        candidate = agents_dir / agent / task_id
        if candidate.exists():
            agent_worktree = candidate
    if agent_worktree is not None and agent_worktree.exists():
        proc3 = _run(
            ["git", "worktree", "remove", "--force", str(agent_worktree)],
            cwd=root,
            capture=True,
            check=False,
        )
        if proc3.returncode != 0:
            msg = (proc3.stderr or proc3.stdout or "").strip()
            print(f"hydra warning: failed to remove worktree {agent_worktree}: {msg}", file=sys.stderr)

    if _git_ref_exists(root, branch_ref):
        proc4 = _run(["git", "branch", "-D", branch], cwd=root, capture=True, check=False)
        if proc4.returncode != 0:
            msg = (proc4.stderr or proc4.stdout or "").strip()
            print(f"hydra warning: failed to delete branch {branch!r}: {msg}", file=sys.stderr)

    print(merged_sha)
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    root = _find_project_root()
    hydra_dir, agents_dir, tasks_dir = _ensure_dirs(root)
    _ensure_config(hydra_dir)

    agent = _sanitize_ref_component(args.agent, label="agent name")
    task_id = _resolve_agent_task(root=root, hydra_dir=hydra_dir, agents_dir=agents_dir, agent=agent, task_opt=args.task)
    _load_task(tasks_dir, task_id)
    branch = f"agent/{agent}/{task_id}"
    branch_ref = f"refs/heads/{branch}"
    if not _git_ref_exists(root, branch_ref):
        raise HydraError(f"Agent branch not found: {branch_ref}")

    to_ref = _rewrite_headish_for_branch(args.to, branch=branch)
    to_commit = _resolve_commit(root, to_ref)

    proc = subprocess.run(  # nosec - CLI tool by design
        ["git", "merge-base", "--is-ancestor", to_commit, branch],
        cwd=str(root),
    )
    if proc.returncode != 0:
        raise HydraError(f"--to {args.to!r} ({to_commit}) is not an ancestor of {branch!r}.")

    agent_worktree = _find_worktree_by_branch(root, branch_ref)
    created_worktree = False
    if agent_worktree is None:
        candidate = agents_dir / agent / task_id
        if candidate.exists():
            agent_worktree = candidate
    if agent_worktree is None:
        wt = hydra_dir / "worktrees" / f"rollback-{agent}-{task_id}-{_now_ts()}"
        wt.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "worktree", "add", str(wt), branch], cwd=root, capture=True, check=True)
        agent_worktree = wt
        created_worktree = True

    try:
        _ensure_worktree_clean(agent_worktree, label=f"Agent worktree ({agent}/{task_id})", allow_untracked=False)
        count_out = _run(["git", "rev-list", "--count", f"{to_commit}..HEAD"], cwd=agent_worktree, capture=True).stdout
        count = int((count_out or "0").strip() or "0")
        if count <= 0:
            print("Nothing to rollback")
            return 0

        proc2 = _run(["git", "revert", "--no-commit", f"{to_commit}..HEAD"], cwd=agent_worktree, capture=True, check=False)
        if proc2.returncode != 0:
            _abort_revert(agent_worktree)
            stderr = (proc2.stderr or "").strip()
            raise HydraError(
                f"Revert conflict while rolling back {branch!r} to {args.to!r} (revert aborted).\n"
                f"To resolve manually: git checkout {branch} && git revert --no-commit {to_commit}..HEAD\n{stderr}"
            )

        env = os.environ.copy()
        env.update(
            {
                "AGENT_ID": agent,
                "TASK_ID": task_id,
                "HYDRA_PROJECT_ROOT": str(root),
                "HYDRA_TASK_FILE": str(_task_path(tasks_dir, task_id)),
                "GIT_AUTHOR_NAME": f"{agent} Agent",
                "GIT_AUTHOR_EMAIL": f"{agent}@agents.local",
                "GIT_COMMITTER_NAME": f"{agent} Agent",
                "GIT_COMMITTER_EMAIL": f"{agent}@agents.local",
            }
        )

        msg = f"Rollback {branch} to {args.to} ({to_commit[:12]})"
        _run(["git", "commit", "-m", msg], cwd=agent_worktree, capture=True, env=env)
        new_sha = _run(["git", "rev-parse", "HEAD"], cwd=agent_worktree, capture=True).stdout.strip()
        print(new_sha)
        return 0
    finally:
        if created_worktree and agent_worktree is not None:
            _run(["git", "worktree", "remove", "--force", str(agent_worktree)], cwd=root, capture=True, check=False)


def cmd_task_new(args: argparse.Namespace) -> int:
    root = _find_project_root()
    _hydra_dir, _agents_dir, tasks_dir = _ensure_dirs(root)
    task = _create_task(tasks_dir, title=args.title, allow=args.allow, explicit_id=args.id)
    print(task.id)
    return 0


def cmd_task_list(args: argparse.Namespace) -> int:
    root = _find_project_root()
    _hydra_dir, _agents_dir, tasks_dir = _ensure_dirs(root)
    paths = sorted(tasks_dir.glob("t*.json"))
    for p in paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            tid = data.get("id", p.stem)
            title = data.get("title", "")
            created = data.get("created", 0)
            print(f"{tid}\t{created}\t{title}")
        except Exception:
            print(p.name)
    return 0


def cmd_task_show(args: argparse.Namespace) -> int:
    root = _find_project_root()
    _hydra_dir, _agents_dir, tasks_dir = _ensure_dirs(root)
    task = _load_task(tasks_dir, args.task_id)
    print(json.dumps(task.__dict__, indent=2, ensure_ascii=False))
    return 0


def cmd_agent_open(args: argparse.Namespace) -> int:
    root = _find_project_root()
    hydra_dir, agents_dir, tasks_dir = _ensure_dirs(root)
    config_path = _ensure_config(hydra_dir)
    
    # Load config to get tmux session name
    config = json.loads(config_path.read_text(encoding="utf-8"))

    agent = _sanitize_ref_component(args.name, label="agent name")
    task_id = _sanitize_task_id(args.task)
    task = _load_task(tasks_dir, task_id)

    worktree = agents_dir / agent / task_id
    branch = f"agent/{agent}/{task_id}"
    base_ref = args.base or _default_base_ref(root)
    project_session = config.get("tmux_session", "hydra")
    window_name = agent  # Use agent name as window name

    files_to_lock = _expand_allow(root, task.allow)

    if args.dry_run:
        if args.lock:
            print("[dry-run] would lock", len(files_to_lock), "paths")
        else:
            print("[dry-run] no locking (optimistic concurrency)")

    # Only acquire locks if --lock is specified
    if args.lock:
        with _connect_db(hydra_dir) as conn:
            _acquire_locks(conn, files=files_to_lock, agent=agent, task=task_id, tmux_session=None)

    try:
        _create_worktree(root, worktree=worktree, branch=branch, base_ref=base_ref, dry_run=args.dry_run)
        if not args.no_shared_deps:
            _share_deps(root, worktree, DEFAULT_SHARED_DEPS, dry_run=args.dry_run)

        # Create symlink to hydra.py for easy access
        hydra_link = worktree / "hydra.py"
        hydra_source = root / "hydra.py"
        if not args.dry_run and hydra_source.exists() and not hydra_link.exists():
            _relative_symlink(hydra_source, hydra_link, dry_run=False)

        if not args.no_tmux and _tmux_available():
            shell = args.shell or os.environ.get("SHELL") or "/bin/bash"
            env_vars = {
                "AGENT_ID": agent,
                "TASK_ID": task_id,
                "HYDRA_PROJECT_ROOT": str(root),
                "HYDRA_TASK_FILE": str(_task_path(tasks_dir, task_id)),
                "GIT_AUTHOR_NAME": f"{agent} Agent",
                "GIT_AUTHOR_EMAIL": f"{agent}@agents.local",
                "GIT_COMMITTER_NAME": f"{agent} Agent",
                "GIT_COMMITTER_EMAIL": f"{agent}@agents.local",
            }
            _start_tmux_window(
                project_session=project_session,
                window_name=window_name,
                worktree=worktree,
                env_vars=env_vars,
                shell=shell,
                dry_run=args.dry_run,
            )
            if not args.dry_run and args.lock:
                with _connect_db(hydra_dir) as conn:
                    _set_locks_tmux_session(conn, agent=agent, task=task_id, tmux_session=project_session)
            print(f"tmux attach -t {project_session}")
        else:
            if not args.no_tmux and not _tmux_available():
                print("hydra warning: tmux not found; created worktree without tmux session", file=sys.stderr)
            print(worktree)
    except Exception:
        if args.lock:
            with _connect_db(hydra_dir) as conn:
                _release_locks(conn, agent=agent, task=task_id)
        raise
    return 0


def cmd_agent_close(args: argparse.Namespace) -> int:
    root = _find_project_root()
    hydra_dir, agents_dir, _tasks_dir = _ensure_dirs(root)

    agent = _sanitize_ref_component(args.name, label="agent name")
    task_id = _sanitize_task_id(args.task)

    # Close Zellij tab or tmux session
    if not args.keep_tmux:
        if _zellij_available():
            # Close Zellij tab
            try:
                if args.dry_run:
                    print(f"[dry-run] Close Zellij tab: {agent}")
                else:
                    # Switch to the agent tab
                    subprocess.run(
                        ["zellij", "action", "go-to-tab-name", agent],
                        check=False,
                        capture_output=True,
                        text=True
                    )
                    # Close the tab
                    subprocess.run(
                        ["zellij", "action", "close-tab"],
                        check=True,
                        capture_output=True,
                        text=True
                    )

                    # Wait and switch back to main tab
                    time.sleep(0.5)
                    subprocess.run(
                        ["zellij", "action", "go-to-tab-name", "main"],
                        check=False,
                        capture_output=True,
                        text=True
                    )
                    print(f"Closed Zellij tab: {agent}")
            except subprocess.CalledProcessError as e:
                print(f"Warning: Failed to close Zellij tab: {e.stderr}")
        elif _tmux_available():
            # Close tmux window
            # Get project session name from config
            config_path = hydra_dir / CONFIG_NAME
            session_name = root.name
            if config_path.exists():
                try:
                    config = json.loads(config_path.read_text(encoding="utf-8"))
                    session_name = config.get("tmux_session", root.name)
                except Exception:
                    pass

            window_target = f"{session_name}:{agent}"
            if args.dry_run:
                print(f"[dry-run] tmux kill-window -t {window_target}")
            else:
                try:
                    subprocess.run(
                        ["tmux", "kill-window", "-t", window_target],
                        check=True,
                        capture_output=True,
                        text=True
                    )
                    print(f"Closed tmux window: {agent}")
                except subprocess.CalledProcessError as e:
                    print(f"Warning: Failed to close tmux window: {e.stderr}")

    released = 0
    with _connect_db(hydra_dir) as conn:
        released = _release_locks(conn, agent=agent, task=task_id)

    if args.remove_worktree:
        worktree = agents_dir / agent / task_id
        cmd = ["git", "worktree", "remove", "--force", str(worktree)]
        if args.dry_run:
            print("[dry-run]", " ".join(cmd))
        else:
            _run(cmd, cwd=root, capture=True)

    print(f"Released {released} locks for {agent}/{task_id}")
    return 0


def cmd_agent_spawn(args: argparse.Namespace) -> int:
    """Spawn an agent (start codex/gemini) in an existing window."""
    root = _find_project_root()
    hydra_dir, agents_dir, tasks_dir = _ensure_dirs(root)

    agent = _sanitize_ref_component(args.name, label="agent name")
    task_id = _sanitize_task_id(args.task)

    # Get worktree path
    worktree = agents_dir / agent / task_id
    if not worktree.exists():
        raise HydraError(f"Worktree not found: {worktree}. Run 'agent open' first.")

    # Get project session name from config
    config_path = hydra_dir / CONFIG_NAME
    session_name = root.name  # Default
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            session_name = config.get("tmux_session", root.name)
        except Exception:
            pass

    # Determine agent type and command
    agent_type = args.type or "codex"
    if agent_type == "codex":
        cmd = "codex --full-auto"
    elif agent_type == "gemini":
        cmd = "gemini --yolo"
    else:
        raise HydraError(f"Unknown agent type: {agent_type}")

    # Send command to existing window
    window_target = f"{session_name}:{agent}"
    try:
        if _tmux_available():
            # Send the command to the window
            subprocess.run(
                ["tmux", "send-keys", "-t", window_target, cmd, "Enter"],
                check=True,
                capture_output=True,
                text=True
            )
            print(f"Created agent window '{agent}' in tmux session '{session_name}'")
            print(f"Working directory: {worktree}")
        else:
            raise HydraError("tmux not found (required for `hydra agent spawn`).")
    except subprocess.CalledProcessError as e:
        raise HydraError(f"Failed to spawn agent: {e.stderr}")

    # Create agent guide file
    if agent_type == "codex":
        guide_file = worktree / "AGENT.md"
        template = AGENT_MD_TEMPLATE
    else:  # gemini
        guide_file = worktree / "GEMINI.md"
        template = GEMINI_MD_TEMPLATE

    if not guide_file.exists():
        guide_file.write_text(template, encoding="utf-8")
        print(f"Created {guide_file}")

    return 0


def cmd_agent_send(args: argparse.Namespace) -> int:
    """Send a message to an agent window."""
    root = _find_project_root()
    hydra_dir, _agents_dir, _tasks_dir = _ensure_dirs(root)

    agent = _sanitize_ref_component(args.name, label="agent name")
    message = args.message

    # Get project session name from config
    config_path = hydra_dir / CONFIG_NAME
    session_name = root.name
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            session_name = config.get("tmux_session", root.name)
        except Exception:
            pass

    # Send message to agent window/tab
    window_target = f"{session_name}:{agent}"
    try:
        if _zellij_available():
            # Use Zellij
            # Switch to agent tab
            subprocess.run(
                ["zellij", "action", "go-to-tab-name", agent],
                check=True,
                capture_output=True,
                text=True
            )
            # Send message
            subprocess.run(
                ["zellij", "action", "write-chars", message],
                check=True,
                capture_output=True,
                text=True
            )
            # Send Enter key
            subprocess.run(
                ["zellij", "action", "write", "13"],  # CR
                check=True,
                capture_output=True,
                text=True
            )
            subprocess.run(
                ["zellij", "action", "write", "10"],  # LF
                check=True,
                capture_output=True,
                text=True
            )
            # Wait 0.5 second before switching back
            time.sleep(0.5)
            # Switch back to main tab
            subprocess.run(
                ["zellij", "action", "go-to-tab-name", "main"],
                check=True,
                capture_output=True,
                text=True
            )
            print(f"Sent message to {agent}")
        elif _tmux_available():
            # Fallback to tmux
            subprocess.run(
                ["tmux", "send-keys", "-t", window_target, "-l", message],
                check=True,
                capture_output=True,
                text=True
            )
            # Longer delay to ensure Codex is ready to receive Enter
            time.sleep(1)
            # Send Enter key twice (first one is newline in multi-line input, second one submits)
            subprocess.run(
                ["tmux", "send-keys", "-t", window_target, "Enter"],
                check=True,
                capture_output=True,
                text=True
            )
            time.sleep(1)
            subprocess.run(
                ["tmux", "send-keys", "-t", window_target, "Enter"],
                check=True,
                capture_output=True,
                text=True
            )
            print(f"Sent message to {agent}")
        else:
            raise HydraError("Neither zellij nor tmux found (required for `hydra agent send`).")
    except subprocess.CalledProcessError as e:
        raise HydraError(f"Failed to send message: {e.stderr}")

    return 0


def cmd_agent_read(args: argparse.Namespace) -> int:
    """Read output from an agent window."""
    root = _find_project_root()
    hydra_dir, _agents_dir, _tasks_dir = _ensure_dirs(root)

    agent = _sanitize_ref_component(args.name, label="agent name")
    lines = args.lines or 50

    # Get project session name from config
    config_path = hydra_dir / CONFIG_NAME
    session_name = root.name
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            session_name = config.get("tmux_session", root.name)
        except Exception:
            pass

    # Capture pane output
    window_target = f"{session_name}:{agent}"
    try:
        if _zellij_available():
            # Use Zellij
            import tempfile
            # Switch to agent tab
            subprocess.run(
                ["zellij", "action", "go-to-tab-name", agent],
                check=True,
                capture_output=True,
                text=True
            )
            # Dump screen to temporary file
            with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt') as tmp:
                tmp_path = tmp.name
            subprocess.run(
                ["zellij", "action", "dump-screen", tmp_path],
                check=True,
                capture_output=True,
                text=True
            )
            # Read and print last N lines
            with open(tmp_path, 'r') as f:
                all_lines = f.readlines()
                output_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                print(''.join(output_lines), end='')
            # Clean up temp file
            Path(tmp_path).unlink()

            # Wait 0.5 second before switching back
            time.sleep(0.5)

            # Switch back to main tab
            subprocess.run(
                ["zellij", "action", "go-to-tab-name", "main"],
                check=True,
                capture_output=True,
                text=True
            )
        elif _tmux_available():
            # Fallback to tmux
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", window_target, "-p", "-S", f"-{lines}"],
                check=True,
                capture_output=True,
                text=True
            )
            print(result.stdout)
        else:
            raise HydraError("Neither zellij nor tmux found (required for `hydra agent read`).")
    except subprocess.CalledProcessError as e:
        raise HydraError(f"Failed to read agent output: {e.stderr}")

    return 0


def cmd_agent_notify(args: argparse.Namespace) -> int:
    """Send a notification message to the main window (Claude Lead)."""
    root = _find_project_root()
    hydra_dir, _agents_dir, _tasks_dir = _ensure_dirs(root)

    message = args.message

    # Get project session name from config
    config_path = hydra_dir / CONFIG_NAME
    session_name = root.name
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            session_name = config.get("tmux_session", root.name)
        except Exception:
            pass

    # Send message to main window
    window_target = f"{session_name}:main"
    try:
        if not _tmux_available():
            raise HydraError("tmux not found (required for `hydra agent notify`).")
        # Send the message as text
        subprocess.run(
            ["tmux", "send-keys", "-t", window_target, "-l", f"[Agent Notification] {message}"],
            check=True,
            capture_output=True,
            text=True
        )
        # Send Enter key
        subprocess.run(
            ["tmux", "send-keys", "-t", window_target, "Enter"],
            check=True,
            capture_output=True,
            text=True
        )
        print(f"Notification sent to main window")
    except subprocess.CalledProcessError as e:
        raise HydraError(f"Failed to send notification: {e.stderr}")

    return 0


def cmd_agent_list(args: argparse.Namespace) -> int:
    """List all agent worktrees."""
    root = _find_project_root()
    hydra_dir, agents_dir, tasks_dir = _ensure_dirs(root)

    # Check if agents directory exists
    if not agents_dir.exists():
        print("No agents found")
        return 0

    # Get all agent directories
    agent_dirs = sorted([d for d in agents_dir.iterdir() if d.is_dir()])

    if not agent_dirs:
        print("No agents found")
        return 0

    # Display header
    print(f"{'Agent':<20} {'Task ID':<15} {'Worktree Path'}")
    print("-" * 80)

    # List each agent and its tasks
    for agent_dir in agent_dirs:
        agent_name = agent_dir.name
        # List all tasks for this agent
        task_dirs = sorted([d for d in agent_dir.iterdir() if d.is_dir()])

        if not task_dirs:
            print(f"{agent_name:<20} {'(no tasks)':<15}")
        else:
            for task_dir in task_dirs:
                task_id = task_dir.name
                worktree_path = task_dir.resolve()
                print(f"{agent_name:<20} {task_id:<15} {worktree_path}")

    return 0


def cmd_locks_list(args: argparse.Namespace) -> int:
    root = _find_project_root()
    hydra_dir, _agents_dir, _tasks_dir = _ensure_dirs(root)
    with _connect_db(hydra_dir) as conn:
        _cleanup_dead_locks(conn)
        rows = _list_locks(conn)
    for f, a, t, ts, s in rows:
        print(f"{f}\t{a}\t{t}\t{ts}\t{s}")
    return 0


def cmd_locks_cleanup(args: argparse.Namespace) -> int:
    root = _find_project_root()
    hydra_dir, _agents_dir, _tasks_dir = _ensure_dirs(root)
    with _connect_db(hydra_dir) as conn:
        conn.execute("BEGIN IMMEDIATE;")
        try:
            released = _cleanup_dead_locks(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    print(f"Released {released} dead locks")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hydra", description="CodeHydra: Multi-agent git worktree manager (v0.1.0, Phase 5)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="Initialize .hydra/, tasks/, and locks DB")
    sp.add_argument("--session", help="Explicit tmux session name (default: project directory name)")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("snapshot", help="Commit a debounced snapshot for an agent")
    sp.add_argument("agent", help="Agent name (e.g. codex-1)")
    sp.add_argument("--task", help="Task id (e.g. t1737123456). Required if agent has multiple tasks.")
    sp.add_argument("--debounce", type=float, default=3.0, help="Seconds to wait after last file write (default: 3)")
    sp.add_argument("--max-wait", type=float, default=60.0, help="Max seconds to wait for debounce (default: 60)")
    sp.set_defaults(func=cmd_snapshot)

    sp = sub.add_parser("changes", help="Show change history from .hydra/journal.jsonl")
    sp.add_argument(
        "--since",
        help="Filter by time (unix seconds, 'YYYY-MM-DD[ HH:MM[:SS]]', or duration like '10 minutes')",
    )
    sp.add_argument("--agent", help="Filter by agent name")
    sp.add_argument("--task", help="Filter by task id like t1737123456")
    sp.set_defaults(func=cmd_changes)

    sp = sub.add_parser("diff", help="Show git diff for an agent")
    sp.add_argument("agent", help="Agent name (e.g. codex-1)")
    sp.add_argument("--task", help="Task id (optional; shows all tasks when omitted)")
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("merge", help="Merge an agent branch into trunk (main/master)")
    sp.add_argument("agent", help="Agent name (e.g. codex-1)")
    sp.add_argument("--task", help="Task id (required if agent has multiple tasks)")
    sp.add_argument("--squash", action="store_true", help="Squash all agent commits into one")
    sp.add_argument("--abort", action="store_true", help="Abort an in-progress merge")
    sp.set_defaults(func=cmd_merge)

    sp = sub.add_parser("rollback", help="Rollback an agent branch by reverting commits (history-preserving)")
    sp.add_argument("agent", help="Agent name (e.g. codex-1)")
    sp.add_argument("--task", help="Task id (required if agent has multiple tasks)")
    sp.add_argument("--to", required=True, help="Rollback target (e.g. HEAD~3, <sha>, or <branch>~N)")
    sp.set_defaults(func=cmd_rollback)

    task = sub.add_parser("task", help="Task management")
    task_sub = task.add_subparsers(dest="task_cmd", required=True)

    sp = task_sub.add_parser("new", help="Create a new task")
    sp.add_argument("title", help="Task title")
    sp.add_argument("--allow", action="append", required=True, help="Allowed path glob (repeatable)")
    sp.add_argument("--id", help="Explicit task id like t1737123456")
    sp.set_defaults(func=cmd_task_new)

    sp = task_sub.add_parser("list", help="List tasks")
    sp.set_defaults(func=cmd_task_list)

    sp = task_sub.add_parser("show", help="Show a task JSON")
    sp.add_argument("task_id", help="Task id like t1737123456")
    sp.set_defaults(func=cmd_task_show)

    agent = sub.add_parser("agent", help="Agent management")
    agent_sub = agent.add_subparsers(dest="agent_cmd", required=True)

    sp = agent_sub.add_parser("open", help="Create worktree and lock files for an agent")
    sp.add_argument("name", help="Agent name (e.g. codex-1)")
    sp.add_argument("--task", required=True, help="Task id (e.g. t1737123456)")
    sp.add_argument("--base", help="Base ref for the agent branch (default: main/master/HEAD)")
    sp.add_argument("--lock", action="store_true", help="Acquire file locks (default: no locking, resolve conflicts at merge)")
    sp.add_argument("--no-tmux", action="store_true", help="Do not create a tmux session")
    sp.add_argument("--shell", help="Shell to run inside tmux (default: $SHELL)")
    sp.add_argument("--no-shared-deps", action="store_true", help="Do not symlink shared deps like node_modules")
    sp.add_argument("--dry-run", action="store_true", help="Print actions without changing anything")
    sp.set_defaults(func=cmd_agent_open)

    sp = agent_sub.add_parser("close", help="Release locks (and optionally close tmux/worktree)")
    sp.add_argument("name", help="Agent name (e.g. codex-1)")
    sp.add_argument("--task", required=True, help="Task id (e.g. t1737123456)")
    sp.add_argument("--keep-tmux", action="store_true", help="Do not kill the tmux session")
    sp.add_argument("--remove-worktree", action="store_true", help="git worktree remove --force")
    sp.add_argument("--dry-run", action="store_true", help="Print actions without changing anything")
    sp.set_defaults(func=cmd_agent_close)

    sp = agent_sub.add_parser("spawn", help="Spawn agent in current session window")
    sp.add_argument("name", help="Agent name (e.g. codex-1)")
    sp.add_argument("--task", required=True, help="Task id (e.g. t1737123456)")
    sp.add_argument("--type", choices=["codex", "gemini"], help="Agent type (default: codex)")
    sp.set_defaults(func=cmd_agent_spawn)

    sp = agent_sub.add_parser("send", help="Send message to agent")
    sp.add_argument("name", help="Agent name (e.g. codex-1)")
    sp.add_argument("message", help="Message to send")
    sp.set_defaults(func=cmd_agent_send)

    sp = agent_sub.add_parser("read", help="Read agent output")
    sp.add_argument("name", help="Agent name (e.g. codex-1)")
    sp.add_argument("--lines", type=int, help="Number of lines to read (default: 50)")
    sp.set_defaults(func=cmd_agent_read)

    sp = agent_sub.add_parser("notify", help="Send notification to main window (Claude Lead)")
    sp.add_argument("message", help="Notification message")
    sp.set_defaults(func=cmd_agent_notify)

    sp = agent_sub.add_parser("list", help="List all agent worktrees")
    sp.set_defaults(func=cmd_agent_list)

    locks = sub.add_parser("locks", help="Inspect and cleanup file locks")
    locks_sub = locks.add_subparsers(dest="locks_cmd", required=True)

    sp = locks_sub.add_parser("list", help="List current locks")
    sp.set_defaults(func=cmd_locks_list)

    sp = locks_sub.add_parser("cleanup", help="Release locks for missing tmux sessions")
    sp.set_defaults(func=cmd_locks_cleanup)

    hook = sub.add_parser("hook", help=argparse.SUPPRESS)
    hook_sub = hook.add_subparsers(dest="hook_cmd", required=True)

    sp = hook_sub.add_parser("commit-msg", help=argparse.SUPPRESS)
    sp.add_argument("msg_file", help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_hook)

    sp = hook_sub.add_parser("pre-commit", help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_hook)

    sp = hook_sub.add_parser("post-commit", help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_hook)

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except HydraError as e:
        print(f"hydra error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
