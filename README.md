# Hydra 🐙

**Multi-Agent Orchestration Tool** — Enable multiple AI agents to work in parallel without conflicts.

[中文文档](README_CN.md)

Hydra creates isolated workspaces for each agent using Git Worktree, supporting task assignment, file locking, and branch merging.

## ✨ Features

- **Isolated Workspaces** — Each agent works in its own Git Worktree, no interference
- **Task Management** — Create, assign, and track tasks
- **File Locking** — Prevent multiple agents from modifying the same file
- **Branch Merging** — Automatically merge agent work results
- **Multiple Integrations** — CLI / MCP Server / OpenClaw Skill

## 📦 Installation

### Option 1: CLI (Recommended)

```bash
# Copy hydra.py to your project
cp hydra.py /your/project/

# Or install globally
cp hydra.py /usr/local/bin/hydra
chmod +x /usr/local/bin/hydra
```

### Option 2: MCP Server (Claude Code / Cursor)

```bash
cd hydra_mcp
pip install -e .

# Configure Claude Code
claude mcp add hydra "python -m hydra_mcp.server"
```

### Option 3: OpenClaw Skill

```bash
# Copy skill to OpenClaw skills directory
cp -r skill/hydra /path/to/openclaw/skills/
```

## 🚀 Quick Start

```bash
# 1. Initialize Hydra in your project
cd /your/project
python hydra.py init

# 2. Create a task
python hydra.py task new "Implement user login" --allow "src/auth/**/*"

# 3. Create workspace for an agent
python hydra.py agent open codex-1 --task t1234567890

# 4. Spawn the agent (e.g., Codex)
python hydra.py agent spawn codex-1 --task t1234567890

# 5. Send task instructions
python hydra.py agent send codex-1 "Please read tasks/t1234567890.md and complete the task"

# 6. Check agent output
python hydra.py agent read codex-1

# 7. Merge completed work
python hydra.py merge codex-1 --task t1234567890

# 8. Close the agent
python hydra.py agent close codex-1 --task t1234567890 --remove-worktree
```

## 📖 Command Reference

### Task Management

```bash
hydra task new "description" --allow "pattern"  # Create task
hydra task list                                  # List tasks
hydra task show <task-id>                        # Show task details
```

### Agent Management

```bash
hydra agent open <name> --task <id>       # Create agent workspace
hydra agent spawn <name> --task <id>      # Start agent
hydra agent send <name> "message"         # Send message
hydra agent read <name>                   # Read output
hydra agent list                          # List all agents
hydra agent close <name> --task <id>      # Close agent
```

### Merge & Locks

```bash
hydra merge <agent> --task <id>           # Merge agent branch
hydra merge <agent> --task <id> --squash  # Squash merge
hydra locks list                          # List file locks
hydra locks cleanup                       # Clean up dead locks
```

## 🏗️ Architecture

```
Project/
├── .hydra/              # Hydra configuration
│   ├── config.json
│   └── locks.db
├── .agents/             # Agent workspaces (Git Worktrees)
│   ├── codex-1/
│   │   └── t1234567890/
│   └── gemini-1/
│       └── t1234567891/
├── tasks/               # Task documents
│   ├── t1234567890.md
│   └── t1234567891.md
└── hydra.py             # CLI entry point
```

## 🔌 Integrations

### Claude Code (MCP)

```json
{
  "mcpServers": {
    "hydra": {
      "command": "python",
      "args": ["-m", "hydra_mcp.server"]
    }
  }
}
```

### OpenClaw

Add to your `TOOLS.md`:
```markdown
## Hydra
Skill: /path/to/skills/hydra/SKILL.md
```

## 📝 Supported Agents

- **Codex** (OpenAI) — `--type codex`
- **Gemini CLI** (Google) — `--type gemini`
- **Claude Code** (Anthropic) — via MCP integration

## 🤝 Contributing

PRs and Issues are welcome!

## 📄 License

MIT

---

*The name "Hydra" comes from the mythical multi-headed serpent — multiple heads working in parallel, cut one off and it grows back.*
