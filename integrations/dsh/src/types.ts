/**
 * The host surfaces this plugin consumes, expressed as the REAL DSH service
 * contracts rather than local restatements of them.
 *
 * History: this file used to declare hand-written copies of every service it
 * touched ("depend on the seam CONTRACTS, not on any specific type-package
 * layout"). That held while every copy was still true, and then stopped
 * holding silently: `@deepseek-ai/dsh-tools` was never declared as a dependency
 * at all, so `npm run build` could not resolve `defineTool` and nothing
 * type-checked the tool definitions against the engine. The copies are now
 * imported from the packages that own them, so a contract change is a compile
 * error here instead of a runtime surprise.
 *
 * Imported types are type-only: they erase at build time, so the plugin keeps
 * exactly one runtime dependency (`@deepseek-ai/dsh-tools`, resolved from the
 * running installation and declared in `peerDependencies`).
 *
 * @module dsh-graphlint/types
 */

import type { ToolDefinition, ToolRunContext } from '@deepseek-ai/dsh-tools'
import type { JsonValue } from '@deepseek-ai/dsh-util-values'

export type { JsonValue, ToolDefinition, ToolRunContext }

/**
 * The slice of the live runtime Agent this plugin reads.
 *
 * `@deepseek-ai/dsh-agent`'s published `Agent` face carries only {@link id};
 * the live instance is augmented (`packages/core/agent/src/runtime-types.ts`)
 * with `session`, `ctx`, and the rest. `session.header.cwd` is the session's
 * ORIGINAL project directory — the correct graphlint analysis root — while the
 * effective directory `ctx.workingDirectory` tracks can move during a session.
 *
 * `id` is what `ctx.jobs.start({ owner })` wants; see `tools/build.ts`.
 */
export interface AgentLike {
  /** Shared agent/session identity (`@deepseek-ai/dsh-agent`). */
  readonly id?: string
  /** Live session, whose immutable header carries the original project cwd. */
  readonly session?: {
    readonly header?: {
      /** Absolute path the session was created in. */
      readonly cwd?: string
    }
  }
}

/**
 * Timer helpers mixed onto a Cordis context by
 * `@deepseek-ai/cordis-plugin-timer` (the `timer` key, declared through
 * `inject`). `timeout` returns the disposer that cancels the pending callback.
 */
export interface TimerService {
  /**
   * Run `callback` once after `delay` milliseconds.
   * @returns the disposer that cancels it.
   */
  timeout(callback: () => void, delay: number): () => void
}

/**
 * The tool registry, narrowed to what this plugin calls.
 *
 * `ToolDefinition` is the real engine type, so every `defineTool` result in
 * `tools/` is checked against the registry's own contract.
 */
export interface ToolsService {
  /**
   * Register a tool globally (or in the calling agent's scope).
   * @param definition - a definition produced by `defineTool`.
   * @returns the disposer that unregisters it.
   */
  register(definition: ToolDefinition): () => void
}

/**
 * Options for `ctx.workingDirectory.ensure` — the supported seam for resolving
 * the directory a session's tools should operate in.
 */
export interface WorkingDirectoryService {
  /**
   * Validate the session's current directory, restoring the original project
   * when it disappeared.
   * @param agent - the live Agent owning the Session.
   * @param signal - cancellation for filesystem inspection.
   * @returns the existing absolute directory.
   */
  ensure(agent: unknown, signal?: AbortSignal): Promise<string>
}

/**
 * The subset of the Cordis context this plugin consumes.
 *
 * The service members are structural, so a host that omits an OPTIONAL one
 * (`workingDirectory` is absent only in a deployment that never mounts the
 * session-directory seam) still satisfies this type; the tools degrade to
 * `process.cwd()` in that case. `tools` and `subprocess` are hard
 * requirements — the plugin declares them in `inject`.
 */
export interface PluginContext {
  tools: ToolsService
  subprocess: {
    /**
     * Resolve one configured executable in the provider's execution world.
     * @param command - absolute executable path or bare PATH name.
     * @param env - explicit environment entries used for lookup.
     * @param signal - aborts local or remote lookup.
     * @returns a canonical executable path.
     */
    resolveExecutable(
      command: string,
      env?: Readonly<Record<string, string>>,
      signal?: AbortSignal,
    ): Promise<string>
    /**
     * Start one managed child process. The returned handle's `collected`
     * readers stay readable after the process exits.
     * @param spec - argv, cwd, stdio dispositions, grace, and cancellation.
     * @returns the live process handle.
     */
    spawn(spec: {
      argv: readonly string[]
      cwd: string
      stdio: {
        stdin: 'ignore'
        stdout: { maxBytes: number }
        stderr: { maxBytes: number }
      }
      graceMs: number
      signal?: AbortSignal
      env?: Record<string, string>
    }): {
      readonly done: Promise<{ exitCode: number | null; signal: string | null }>
      readonly collected?: {
        stdout?: { readFrom(fromByte: number): { text: string; nextOffset: number; lossy: boolean } }
        stderr?: { readFrom(fromByte: number): { text: string; nextOffset: number; lossy: boolean } }
      }
      terminate(): void
    }
  }
  /**
   * Filesystem seam, used only to probe project-local virtualenv entry points.
   * Optional so a host without it simply reports "CLI not found on PATH".
   */
  fs?: {
    resolve(
      path: string,
      opts?: { cwd?: string; signal?: AbortSignal },
    ): Promise<{ displayPath?: string } | undefined>
    stat(target: unknown, signal?: AbortSignal): Promise<{ type?: string } | undefined>
  }
  /**
   * Skill registry: this plugin contributes the `graphlint` skill through the
   * runtime-registration entry point.
   */
  skills: {
    register(skill: {
      name: string
      description: string
      whenToUse?: string
      content: string
      source?: string
    }): () => void
  }
  /**
   * Background-job registry: `graphlint_build` runs a full rebuild as a job.
   */
  jobs: {
    /**
     * Register and start one background job.
     * @param spec - kind, label, owning session id, output cap, and starter.
     * @returns the registry-issued job id.
     */
    start(spec: {
      kind: string
      label: string
      outputLimitBytes?: number
      /** Owning session id — the STRING id, not the Agent object. */
      owner?: string
      run(): {
        cancel(reason?: string): void
        done: Promise<{ status: 'completed' | 'killed' | 'failed'; detail?: string; result?: string }>
        readOutput?(): string
      }
    }): string
  }
  /** Disposable timer helpers — see {@link TimerService}. */
  timer: TimerService
  /**
   * Session working directory (optional seam); absent in a deployment that
   * does not mount `@deepseek-ai/dsh-working-directory`.
   */
  workingDirectory?: WorkingDirectoryService
  /**
   * Cordis service lookup. Used only to probe peer plugins that must never
   * become a hard dependency — see `secondary.ts`. Declared optional so a host
   * that omits the mixin degrades to "not installed" instead of throwing.
   */
  get?(name: string): unknown
}
