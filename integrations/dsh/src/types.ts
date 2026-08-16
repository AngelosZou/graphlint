/**
 * Minimal surfaces of the DSH host services this plugin consumes.
 *
 * Declared locally on purpose: the plugin depends on the seam CONTRACTS, not
 * on any specific type-package layout, so a @deepseek-ai/* type reshuffle
 * cannot break compilation while the runtime contract stays compatible.
 */

/** JSON-compatible value, mirroring the DSH tool-result boundary. */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }

export interface SubprocessOutputReader {
  readFrom(offset: number): { text: string; nextOffset: number; lossy: boolean; spillPath?: string }
}

export interface SubprocessOutcome {
  exitCode: number | null
  signal: string | null
}

export interface SubprocessHandle {
  readonly pid: number
  readonly done: Promise<SubprocessOutcome>
  readonly collected?: {
    stdout?: SubprocessOutputReader
    stderr?: SubprocessOutputReader
  }
  terminate(): void
}

export interface SubprocessSpawnSpec {
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
}

export interface SubprocessService {
  spawn(spec: SubprocessSpawnSpec): SubprocessHandle
  resolveExecutable(command: string): Promise<string>
}

export interface FsTarget {}

export interface FsInfo {}

export interface FsService {
  resolve(path: string, opts: { cwd?: string }): Promise<FsTarget>
  stat(target: FsTarget): Promise<FsInfo | undefined>
}

/** Shape of the execution context handed to tool `execute` handlers. */
export interface ToolExecutionLike {
  agent?: {
    session?: {
      header?: {
        cwd?: string
      }
    }
  }
  signal?: AbortSignal
}

export interface TimerLike {
  timeout(callback: () => void, delay: number): () => void
}

export interface SkillRegistration {
  name: string
  description: string
  whenToUse?: string
  content: string
  source: string
  invocation?: {
    modelInvocable: boolean
    userInvocable: boolean
  }
}

export interface SkillsService {
  register(skill: SkillRegistration): () => void
}

export interface JobOutcome {
  status: 'completed' | 'killed' | 'failed'
  detail?: string
  output?: string
}

export interface JobHooks {
  cancel(reason?: string): void
  done: Promise<JobOutcome>
  readOutput?(): string
}

export interface JobStart {
  kind: string
  label: string
  outputLimitBytes?: number
  owner?: unknown
  run(): JobHooks
}

export interface JobsService {
  start(spec: JobStart): string
}

export interface ToolsService {
  register(definition: unknown): () => void
}

/** The subset of the Cordis context this plugin consumes. */
export interface PluginContext {
  tools: ToolsService
  subprocess: SubprocessService
  fs: FsService
  skills: SkillsService
  jobs: JobsService
  timer: TimerLike
}
