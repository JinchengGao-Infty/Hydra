# Hydra MCP Server

Claude Code / Cursor 等支持 MCP 的工具可以通过此 Server 使用 Hydra。

## 安装

```bash
cd hydra_mcp
pip install -e .
```

## 配置 Claude Code

```bash
claude mcp add hydra "python -m hydra_mcp.server"
```

或手动编辑 `~/.claude.json`：

```json
{
  "mcpServers": {
    "hydra": {
      "command": "python",
      "args": ["-m", "hydra_mcp.server"],
      "cwd": "/path/to/Hydra-opensource"
    }
  }
}
```

## 可用工具

| 工具 | 说明 |
|------|------|
| `hydraInfo()` | 查看 Hydra 版本和路径 |
| `hydraSetProject(projectRoot)` | 设置项目根目录 |
| `hydraInit(projectRoot, session?, installHydraPy?)` | 初始化项目 |
| `hydraRun(args, projectRoot?)` | 执行任意 hydra.py 命令 |

## 使用示例

```javascript
// 初始化项目
hydraInit({ projectRoot: "/path/to/project" })

// 创建任务
hydraRun({ args: ["task", "new", "实现功能", "--allow", "src/**/*"] })

// 打开 Agent
hydraRun({ args: ["agent", "open", "codex-1", "--task", "t001"] })

// 启动 Agent
hydraRun({ args: ["agent", "spawn", "codex-1", "--task", "t001"] })

// 发送消息
hydraRun({ args: ["agent", "send", "codex-1", "请完成任务"] })

// 读取输出
hydraRun({ args: ["agent", "read", "codex-1"] })

// 合并
hydraRun({ args: ["merge", "codex-1", "--task", "t001"] })
```
