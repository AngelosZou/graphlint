import { defineTool } from '@deepseek-ai/dsh-tools'

import type { JsonValue, PluginContext, ToolExecutionLike } from '../types.js'
import { queryArgv } from '../args.js'
import { failureText, parseQueryOutput, renderQueryText, type QuerySuccess } from '../parse.js'
import { resolveGraphlint } from '../python.js'
import { guardRoot, sessionCwd } from '../root.js'
import { DEFAULT_LIMITS, runGraphlint } from '../runner.js'

const ROOT_DESCRIPTION =
  'Project root directory to analyze. Defaults to the session working directory. ' +
  'Only pass the working directory itself or one of its subdirectories — scanning a high-level root ' +
  '(such as a user home directory) builds a huge index and can block for many minutes.'

interface QueryArgs {
  root_dir?: string
  warn_types?: string
  include_tests?: boolean
  graph_id?: number
  public_as_entry?: boolean
}

export function registerQueryTool(ctx: PluginContext): void {
  ctx.tools.register(
    defineTool({
      name: 'graphlint_query',
      description:
        'Query the graphlint dependency-graph index for dead code and other warnings. ' +
        'Auto-incremental rebuild on first use; install the CLI with `pip install graphlint` if missing. ' +
        ROOT_DESCRIPTION +
        ' Returns the parsed query result: result.graphs (graph_id, entry, node_count, edge_count, warnings, ' +
        'is_dead_code, is_unreachable), result.total_graphs, result.has_more, result.warnings_summary.',
      parameters: {
        root_dir: { type: 'string', description: ROOT_DESCRIPTION },
        warn_types: {
          type: 'string',
          description: 'Comma-separated warning types to filter, e.g. "dead_code" or "dead_code,circular_ref".',
        },
        include_tests: { type: 'boolean', description: 'Include test files in the analysis (default false).' },
        graph_id: {
          type: 'number',
          description: 'Return full detail for one specific dependency graph (connected component) by id.',
        },
        public_as_entry: {
          type: 'boolean',
          description: 'Treat all public items (Rust pub / C# public) as entry points for library analysis.',
        },
      },
      output: {
        schema: { type: 'object', additionalProperties: true },
        render(_args, value: unknown) {
          const v = value as { error?: string } | null
          if (!v || typeof v !== 'object' || typeof v.error === 'string') {
            const text =
              v && typeof v.error === 'string' ? failureText({ ok: false, error: v.error, exitCode: null }) : String(value)
            return [{ type: 'text', text }]
          }
          return [{ type: 'text', text: renderQueryText(v as QuerySuccess).join('\n') }]
        },
      },
      timeoutMs: 120_000,
      async execute(args, exec): Promise<Record<string, JsonValue>> {
        const typed = (args ?? {}) as QueryArgs
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
          queryArgv(exe, {
            rootDir,
            warnTypes: typed.warn_types,
            includeTests: typed.include_tests,
            graphId: typed.graph_id,
            publicAsEntry: typed.public_as_entry,
          }),
          rootDir,
          DEFAULT_LIMITS,
          (exec as ToolExecutionLike | undefined)?.signal,
        )
        if (out.timedOut) {
          return { error: `graphlint query timed out after ${DEFAULT_LIMITS.doneCapMs}ms; the process tree was terminated.` }
        }
        return parseQueryOutput(out.stdout, out.stderr, out.exitCode)
      },
    }),
  )
}
