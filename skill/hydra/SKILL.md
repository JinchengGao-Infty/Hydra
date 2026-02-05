# Hydra Skill for OpenClaw

多 Agent 编排工具，通过 Git Worktree 让多个 AI Agent 并行工作。

## 使用方法

### 初始化项目

```bash
cd /path/to/project
python hydra.py init
```

### 创建任务

```bash
python hydra.py task new "任务描述" --allow "src/**/*"
```

`--allow` 指定 Agent 可以修改的文件范围（glob 模式）。

### 完整工作流

```bash
# 1. 创建任务
python hydra.py task new "实现功能 X" --allow "src/**/*" --id t001

# 2. 打开 Agent 工作空间（创建独立分支）
python hydra.py agent open codex-1 --task t001

# 3. 启动 Agent
python hydra.py agent spawn codex-1 --task t001

# 4. 发送任务
python hydra.py agent send codex-1 "请完成 tasks/t001.md 中的任务"

# 5. 查看输出（快照，看一眼就返回）
python hydra.py agent read codex-1

# 6. 完成后合并
python hydra.py merge codex-1 --task t001

# 7. 关闭并清理
python hydra.py agent close codex-1 --task t001 --remove-worktree
```

### 常用命令

| 命令 | 说明 |
|------|------|
| `hydra task list` | 列出所有任务 |
| `hydra task show <id>` | 查看任务详情 |
| `hydra agent list` | 列出所有 Agent |
| `hydra agent read <name>` | 读取 Agent 输出 |
| `hydra locks list` | 列出文件锁 |
| `hydra locks cleanup` | 清理死锁 |

### Agent 类型

```bash
# Codex（默认）
python hydra.py agent spawn codex-1 --task t001

# Gemini CLI
python hydra.py agent spawn gemini-1 --task t001 --type gemini
```

## 注意事项

1. **每个任务用独立分支** — `agent open` 会创建 worktree
2. **不要循环检查** — `agent read` 看一眼就返回，不要轮询
3. **完成后必须 close** — 释放锁，清理 worktree
4. **重型任务委托** — 复杂任务交给 Codex/Gemini，不要自己写大量代码
