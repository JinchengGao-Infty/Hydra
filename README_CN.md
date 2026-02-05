# Hydra 🐙

**多 Agent 编排工具** — 让多个 AI Agent 并行工作，互不干扰。

[English](README.md)

Hydra 通过 Git Worktree 为每个 Agent 创建独立的工作空间，支持任务分配、文件锁定、分支合并等功能。

## ✨ 特性

- **独立工作空间** — 每个 Agent 在自己的 Git Worktree 中工作，互不干扰
- **任务管理** — 创建、分配、追踪任务
- **文件锁定** — 防止多个 Agent 同时修改同一文件
- **分支合并** — 自动合并 Agent 的工作成果
- **多种接入方式** — CLI / MCP Server / OpenClaw Skill

## 📦 安装方式

### 方式一：CLI（推荐）

```bash
# 复制 hydra.py 到你的项目
cp hydra.py /your/project/

# 或者全局安装
cp hydra.py /usr/local/bin/hydra
chmod +x /usr/local/bin/hydra
```

### 方式二：MCP Server（Claude Code / Cursor 等）

```bash
cd hydra_mcp
pip install -e .

# 配置 Claude Code
claude mcp add hydra "python -m hydra_mcp.server"
```

### 方式三：OpenClaw Skill

```bash
# 复制 skill 到 OpenClaw skills 目录
cp -r skill/hydra /path/to/openclaw/skills/
```

## 🚀 快速开始

```bash
# 1. 在项目中初始化 Hydra
cd /your/project
python hydra.py init

# 2. 创建任务
python hydra.py task new "实现用户登录功能" --allow "src/auth/**/*"

# 3. 为 Agent 创建工作空间
python hydra.py agent open codex-1 --task t1234567890

# 4. 启动 Agent（以 Codex 为例）
python hydra.py agent spawn codex-1 --task t1234567890

# 5. 发送任务指令
python hydra.py agent send codex-1 "请阅读 tasks/t1234567890.md 并完成任务"

# 6. 查看 Agent 输出
python hydra.py agent read codex-1

# 7. 合并完成的工作
python hydra.py merge codex-1 --task t1234567890

# 8. 关闭 Agent
python hydra.py agent close codex-1 --task t1234567890 --remove-worktree
```

## 📖 命令参考

### 任务管理

```bash
hydra task new "描述" --allow "pattern"  # 创建任务
hydra task list                           # 列出任务
hydra task show <task-id>                 # 查看任务详情
```

### Agent 管理

```bash
hydra agent open <name> --task <id>       # 创建 Agent 工作空间
hydra agent spawn <name> --task <id>      # 启动 Agent
hydra agent send <name> "message"         # 发送消息
hydra agent read <name>                   # 读取输出
hydra agent list                          # 列出所有 Agent
hydra agent close <name> --task <id>      # 关闭 Agent
```

### 合并与锁

```bash
hydra merge <agent> --task <id>           # 合并 Agent 分支
hydra merge <agent> --task <id> --squash  # 压缩合并
hydra locks list                          # 列出文件锁
hydra locks cleanup                       # 清理死锁
```

## 🏗️ 架构

```
Project/
├── .hydra/              # Hydra 配置
│   ├── config.json
│   └── locks.db
├── .agents/             # Agent 工作空间（Git Worktree）
│   ├── codex-1/
│   │   └── t1234567890/
│   └── gemini-1/
│       └── t1234567891/
├── tasks/               # 任务文档
│   ├── t1234567890.md
│   └── t1234567891.md
└── hydra.py             # CLI 入口
```

## 🔌 集成

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

在 `TOOLS.md` 中添加：
```markdown
## Hydra
Skill: /path/to/skills/hydra/SKILL.md
```

## 📝 支持的 Agent

- **Codex** (OpenAI) — `--type codex`
- **Gemini CLI** (Google) — `--type gemini`
- **Claude Code** (Anthropic) — 通过 MCP 集成

## 🤝 贡献

欢迎 PR 和 Issue！

## 📄 License

MIT

---

*名字寓意：九头蛇（Hydra）— 多头并行，砍掉一个还能再生。*
