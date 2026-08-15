import { defineTool } from '@deepseek-ai/dsh-tools'

import type { JsonValue, PluginContext, ToolExecutionLike } from '../types.js'
import { configArgv, type ConfigAction } from '../args.js'
import { resolveGraphlint } from '../python.js'
import { guardRoot, sessionCwd } from '../root.js'
import { runGraphlint } from '../runner.js'

const ROOT_DESCRIPTION =
  'Project root directory whose .graphlint/config.json is read or updated. Defaults to the session working directory. ' +
  'Only pass the working directory itself or one of its subdirectories.'

interface ConfigArgs {
  action?: string
  key?: string
  value?: string
  rule_json?: string
  name?: string
  exclude_pattern?: string
  root_dir?: string
}

const CONFIG_ACTIONS = new Set([
  'show',
  'get',
  'set',
  'add-entry-rule',
  'remove-entry-rule',
  'add-exclude',
  'remove-exclude',
])

const LIMITS = { doneCapMs: 25_000, graceMs: 10_000 }

export function registerConfigTool(ctx: PluginContext): void {
  ctx.tools.register(
    defineTool({
      name: 'graphlint_config',
      description:
        'Read or update the project .graphlint/config.json via the graphlint CLI (runs `graphlint config` with the ' +
        'project root as its working directory). ' +
        ROOT_DESCRIPTION,
      parameters: {
        action: {
          type: 'string',
          description:
            'show: display the full effective config; get: read one key; set: write one key/value pair; ' +
            'add-entry-rule: add a custom entry rule (needs rule_json); remove-entry-rule: remove a rule (needs name); ' +
            'add-exclude / remove-exclude: add or remove an exclude pattern (needs exclude_pattern).',
        },
        key: { type: 'string', description: 'Config key, required for get/set.' },
        value: {
          type: 'string',
          description: 'New value for set (pass lists/objects as compact JSON text).',
        },
        rule_json: {
          type: 'string',
          description:
            'JSON rule for add-entry-rule, e.g. {"name":"my_service","ast_pattern":"class_instantiation:FastAPI","file_pattern":"**/service.py"}.',
        },
        name: { type: 'string', description: 'Rule name for remove-entry-rule.' },
        exclude_pattern: { type: 'string', description: 'Pattern for add-exclude / remove-exclude.' },
        root_dir: { type: 'string', description: ROOT_DESCRIPTION },
      },
      output: {
        schema: { type: 'object', additionalProperties: true },
        render(_args, value: unknown) {
          const v = value as { error?: string; ok?: boolean; stdout?: string; stderr?: string } | null
          if (v && typeof v.error === 'string') return [{ type: 'text', text: `[graphlint] error: ${v.error}` }]
          const stdout = v && typeof v.stdout === 'string' ? v.stdout : ''
          const stderr = v && typeof v.stderr === 'string' ? v.stderr : ''
          return [{ type: 'text', text: stdout || stderr || '[graphlint] config ok' }]
        },
      },
      timeoutMs: 30_000,
      async execute(args, exec): Promise<Record<string, JsonValue>> {
        const typed = (args ?? {}) as ConfigArgs
        const requested = typeof typed.action === 'string' ? typed.action : 'show'
        const action: ConfigAction = CONFIG_ACTIONS.has(requested) ? (requested as ConfigAction) : 'show'
        const sessionRoot = sessionCwd(exec as ToolExecutionLike | undefined)
        let rootDir: string
        try {
          rootDir = guardRoot(typed.root_dir, sessionRoot)
        } catch (err) {
          return { error: err instanceof Error ? err.message : String(err) }
        }
        const exe = await resolveGraphlint(ctx.subprocess, ctx.fs, rootDir)
        if (!exe) return { error: 'graphlint CLI not found. Install with: pip install graphlint' }
        const out = await runGraphlint(
          ctx.subprocess,
          ctx.timer,
          configArgv(exe, action, {
            key: typed.key,
            value: typed.value,
            ruleJson: typed.rule_json,
            name: typed.name,
            excludePattern: typed.exclude_pattern,
          }),
          rootDir,
          LIMITS,
          (exec as ToolExecutionLike | undefined)?.signal,
        )
        if (out.timedOut) return { error: `graphlint config timed out after ${LIMITS.doneCapMs}ms.` }
        return {
          ok: out.exitCode === 0,
          exit_code: out.exitCode,
          stdout: out.stdout.slice(0, 4000),
          stderr: out.stderr.slice(0, 1000),
        }
      },
    }),
  )
}
