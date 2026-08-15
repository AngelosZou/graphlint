# Agent 集成

Graphlint 为 AI 编码 Agent 提供三种安装渠道：

1. **Skill 安装（默认，推荐）** — 将规范 skill 文档以 `SKILL.md` 形式写入新兴的跨 Agent skill 目录。不修改 Agent 自身的配置文件，兼容所有读取 `~/.agents/skills` 约定的 Agent。
2. **DeepSeek Harness 插件（DSH 环境推荐）** — 将 `dsh-graphlint` bundle（原生工具 + skill）安装到 DSH profile。工具化集成比单纯的 skill 文件更稳健：结构化结果、后台任务构建、工作目录守卫。
3. **提示词注入** — 将提示词块注入 Agent 配置文件（`AGENTS.md`、`CLAUDE.md` 等）。通过 `install prompt` 使用。

## 安装 Skill（默认，推荐）

```bash
graphlint install
# 或显式指定：graphlint install skill
```

写入 `~/.agents/skills/graphlint/SKILL.md`（YAML frontmatter 包含 `name`、`description`，以及用于更新跟踪的 `version` 字段）。

| 选项 | 行为 |
|------|------|
| `--targets agents`（默认） | `~/.agents/skills/graphlint/SKILL.md` |
| `--targets claude` | `~/.claude/skills/graphlint/SKILL.md`（Claude Code 约定） |
| `--targets all` / `--targets agents,claude` | 两个目录都写入 |

重复运行 `install` 会报告"已是最新版本"或升级旧版本。skill 内容刻意保持简洁，只涵盖用途最广的核心内容：

| 部分 | 内容 |
|------|------|
| **使用场景** | 何时运行 graphlint — 修改后清理、分析前审计 |
| **核心命令** | `query`（自动增量构建）、`query --json`、`query -g <id>`、`config show`；仅当 query 结果异常时才用 `build --force` |
| **关键参数** | `-g`/`--graph-id`、`-j`/`--json`、`-w`/`--warn-types`、`-C`、`-R`/`--reachability`、`--public-as-entry`、`-t`、`--dead-code-tests`、`--sort-by`、`--fail-on`、build 的 `-f`/`-P` |
| **自定义入口规则** | `config add-entry-rule` / `remove-entry-rule` / `add-exclude`，适配项目框架约定 |
| **使用示例** | 重构后检查、按严重度排序死代码、图详情、CI 门禁 |
| **局限性** | 仅静态分析（动态引用盲区）、全量构建耗时 |

## 安装 DeepSeek Harness 插件（DSH 环境推荐）

```bash
graphlint install dsh --profile web
```

等价于 `dsh plugin --profile web add dsh-graphlint`。使用 `--local [PATH]` 可链接本地 `integrations/dsh` 仓库而非 npm 包（默认取仓库根目录下的 `./integrations/dsh`）。完成后请重启 `dsh web` 并刷新浏览器页面。

在 DSH 环境中，插件工具（`graphlint_query` / `graphlint_build` / `graphlint_config`）是主要接口：它们在会话工作目录内运行、返回结构化结果、拒绝不安全的根目录 — 插件在工具旁注册自己的 `graphlint` skill，与基于文件的 `SKILL.md` 安装相互独立。

## 安装提示词

```bash
graphlint install prompt
```

交互式选择器将提示词块注入全局配置文件，用 HTML 注释（`<!-- graphlint:start -->` … `<!-- graphlint:end -->`）包裹以便检测和干净移除：

| 工具 ID | 显示名称 | 全局配置文件 |
|---------|---------|-------------|
| `opencode` | OpenCode CLI | `~/.config/opencode/AGENTS.md` |
| `cursor` | Cursor Editor | `~/.cursorrules` |
| `codex` | Codex CLI | `~/.codex/rules/graphlint.md` |
| `cc` | Claude Code (CLI) | `~/.claude/CLAUDE.md` |

## 提示词命令

如果您使用的 Agent 工具不在支持列表中，或者您更倾向于手动配置，可以使用以下命令将提示词复制到粘贴板：

```bash
graphlint prompt
```

这会复制与 `install` 相同的内容 — 将其粘贴到您的 Agent 系统提示词或配置文件中即可。

## 卸载

```bash
graphlint uninstall              # 移除已安装的 skill
graphlint uninstall --targets all
graphlint uninstall prompt       # 移除注入的提示词块
```

`uninstall` 移除 graphlint 写入的 `SKILL.md`（目录为空时一并删除）；同路径下非 graphlint 安装的文件会被跳过。`uninstall prompt` 扫描 Agent 配置文件中的标记块并交互式移除。

## 单一内容源

规范 skill 文档随 Python 包一起发布，位于 `graphlint/skill.md`（含 YAML frontmatter）。所有渠道均由此派生：`install` 原样写入（附加 `version` 字段）、`prompt` 去除 frontmatter、DeepSeek Harness 插件在构建期内嵌同一内容 — 两侧均有同步测试防止漂移。
