import { defineTool } from '@deepseek-ai/dsh-tools'

import type { JobHooks, JsonValue, PluginContext, ToolExecutionLike } from '../types.js'
import { buildArgv } from '../args.js'
import { resolveGraphlint } from '../python.js'
import { guardRoot, sessionCwd } from '../root.js'

const ROOT_DESCRIPTION =
  'Project root directory to build the index for. Defaults to the session working directory. ' +
  'Only pass the working directory itself or one of its subdirectories — building an index for a high-level root ' +
  '(such as a user home directory) can take many minutes.'

interface BuildArgs {
  root_dir?: string
  force?: boolean
}

const OUTPUT_LIMIT_BYTES = 64_000

export function registerBuildTool(ctx: PluginContext): void {
  ctx.tools.register(
    defineTool({
      name: 'graphlint_build',
      description:
        'Build or rebuild the graphlint index as a background job; poll it with job_output using the returned job id. ' +
        'Runs `graphlint build` with the project root as its working directory. ' +
        ROOT_DESCRIPTION,
      parameters: {
        root_dir: { type: 'string', description: ROOT_DESCRIPTION },
        force: { type: 'boolean', description: 'Force a full index rebuild (default: incremental).' },
      },
      output: {
        schema: { type: 'object', additionalProperties: true },
        render(_args, value: unknown) {
          const v = value as { error?: string; job_id?: string } | null
          if (v && typeof v.error === 'string') return [{ type: 'text', text: `[graphlint] error: ${v.error}` }]
          const id = v && typeof v.job_id === 'string' ? v.job_id : 'unknown'
          return [
            {
              type: 'text',
              text: `[graphlint] build started as background job ${id}. Poll with job_output; a first-time full build can take minutes.`,
            },
          ]
        },
      },
      timeoutMs: 15_000,
      async execute(args, exec): Promise<Record<string, JsonValue>> {
        const typed = (args ?? {}) as BuildArgs
        const sessionRoot = sessionCwd(exec as ToolExecutionLike | undefined)
        let rootDir: string
        try {
          rootDir = guardRoot(typed.root_dir, sessionRoot)
        } catch (err) {
          return { error: err instanceof Error ? err.message : String(err) }
        }
        const exe = await resolveGraphlint(ctx.subprocess, ctx.fs, rootDir)
        if (!exe) return { error: 'graphlint CLI not found. Install with: pip install graphlint' }
        const handle = ctx.subprocess.spawn({
          argv: buildArgv(exe, typed.force === true),
          cwd: rootDir,
          stdio: {
            stdin: 'ignore',
            stdout: { maxBytes: 1_048_576 },
            stderr: { maxBytes: 262_144 },
          },
          graceMs: 15_000,
          signal: (exec as ToolExecutionLike | undefined)?.signal,
          env: { PYTHONIOENCODING: 'utf-8' },
        })
        const jobId = ctx.jobs.start({
          kind: 'graphlint-build',
          label: `graphlint build${typed.force === true ? ' --force' : ''} in ${rootDir}`,
          outputLimitBytes: OUTPUT_LIMIT_BYTES,
          owner: (exec as { agent?: unknown } | undefined)?.agent,
          run: (): JobHooks => {
            let stdoutCursor = 0
            let stderrCursor = 0
            return {
              cancel: () => handle.terminate(),
              done: handle.done.then(
                (outcome) =>
                  outcome.exitCode === 0
                    ? { status: 'completed' as const, detail: 'index build finished' }
                    : outcome.exitCode === null
                      ? { status: 'killed' as const, detail: 'process tree terminated' }
                      : { status: 'failed' as const, detail: `exit code: ${outcome.exitCode}` },
                (err) => ({
                  status: 'failed' as const,
                  detail: String((err as { message?: string })?.message ?? err),
                }),
              ),
              readOutput: () => {
                const parts: string[] = []
                const stdoutReader = handle.collected?.stdout
                if (stdoutReader) {
                  const read = stdoutReader.readFrom(stdoutCursor)
                  stdoutCursor = read.nextOffset
                  if (read.text.length > 0) parts.push(read.text)
                }
                const stderrReader = handle.collected?.stderr
                if (stderrReader) {
                  const read = stderrReader.readFrom(stderrCursor)
                  stderrCursor = read.nextOffset
                  if (read.text.length > 0) parts.push(read.text)
                }
                return parts.join('')
              },
            }
          },
        })
        return { job_id: jobId }
      },
    }),
  )
}
