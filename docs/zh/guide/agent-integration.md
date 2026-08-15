# Agent 集成

Graphlint 提供 `install` 和 `uninstall` 子命令，将使用提示词注入到您的 AI 编码工具的**全局配置**中。安装后，您使用该工具打开的每个项目都将自动获得 graphlint 的使用指南 — 无需重复配置。

## 提示词命令

如果您使用的 Agent 工具不在支持列表中，或者您更倾向于手动配置，可以使用以下命令将提示词复制到粘贴板：

```bash
graphlint prompt
```

这会复制与 `install` 命令相同的 `AGENT_PROMPT` 内容 — 将其粘贴到您的 Agent 系统提示词或配置文件中即可。

## 安装

```bash
graphlint install
```

您将看到交互式提示，列出支持的工具及其全局配置路径：

```
Select agent tool(s) to install graphlint prompt:

  [1] OpenCode CLI          ~/.config/opencode/AGENTS.md
      Global AGENTS.md — read by opencode in every project
  [2] Cursor Editor         ~/.cursorrules
      Global .cursorrules — applies to all Cursor projects
  [3] Codex CLI             ~/.codex/rules/graphlint.md
      Global rules directory — recognized by Codex CLI
  [4] Claude Code (CLI)     ~/.claude/CLAUDE.md
      Global CLAUDE.md — read by Claude Code in every project

Enter numbers separated by comma (e.g. 1,3) or 'all':
```

选择一个或多个工具。提示词内容被 HTML 注释包裹（`<!-- graphlint:start -->` … `<!-- graphlint:end -->`），便于检测和干净移除。

### 安装内容

提示词刻意保持简洁，只涵盖用途最广的核心内容：

| 部分 | 内容 |
|------|------|
| **使用场景** | 何时运行 graphlint — 修改后清理、分析前审计 |
| **核心命令** | `query`（自动增量构建）、`query --json`、`query -g <id>`、`config show`；仅当 query 结果异常时才用 `build --force` |
| **关键参数** | `-g`/`--graph-id`、`-j`/`--json`、`-w`/`--warn-types`、`-C`、`-R`/`--reachability`、`--public-as-entry`、`-t`、`--dead-code-tests`、`--sort-by`、`--fail-on`、build 的 `-f`/`-P` |
| **自定义入口规则** | `config add-entry-rule` / `remove-entry-rule` / `add-exclude`，适配项目框架约定 |
| **使用示例** | 重构后检查、按严重度排序死代码、图详情、CI 门禁 |
| **局限性** | 仅静态分析（动态引用盲区）、全量构建耗时 |

## 卸载

```bash
graphlint uninstall
```

扫描全局配置文件中的 `graphlint:start`/`graphlint:end` 标记，显示已安装的工具。选择要移除的工具即可。

## 提示词文件

规范 skill 文档随 Python 包一起发布，位于 `graphlint/skill.md`（含 YAML frontmatter）。`install` 与 `prompt` 的文本均由此派生（去除 frontmatter），所有分发渠道共享同一内容源。

## 支持的 Agent 工具

| 工具 ID | 显示名称 | 全局配置文件 |
|---------|---------|-------------|
| `opencode` | OpenCode CLI | `~/.config/opencode/AGENTS.md` |
| `cursor` | Cursor Editor | `~/.cursorrules` |
| `codex` | Codex CLI | `~/.codex/rules/graphlint.md` |
| `cc` | Claude Code (CLI) | `~/.claude/CLAUDE.md` |

> **注意：** 这些是**全局**配置路径。如果您希望按项目安装，请将 `graphlint prompt` 输出的提示词（或已安装包中的规范 `graphlint/skill.md`）复制到项目本地的配置文件中（如 `AGENTS.md`、`CLAUDE.md`、`.cursorrules`）。
