import type { SubprocessService, TimerLike } from './types.js'

export interface RunLimits {
  /** Upper bound for waiting on process exit before terminating the tree. */
  doneCapMs: number
  /** Grace period the subprocess service uses between SIGTERM and SIGKILL. */
  graceMs: number
}

export const DEFAULT_LIMITS: RunLimits = { doneCapMs: 120_000, graceMs: 15_000 }

export interface RunOutcome {
  exitCode: number | null
  stdout: string
  stderr: string
  /** True when the done cap fired and the process tree was terminated. */
  timedOut: boolean
}

function withTimeout<T>(timer: TimerLike, promise: Promise<T>, ms: number): Promise<T | 'timeout'> {
  return new Promise((resolvePromise) => {
    const cancel = timer.timeout(() => resolvePromise('timeout'), ms)
    promise.then(
      (value) => {
        cancel()
        resolvePromise(value)
      },
      () => {
        cancel()
        resolvePromise('timeout')
      },
    )
  })
}

function readAll(reader: { readFrom(offset: number): { text: string } } | undefined): string {
  if (!reader) return ''
  return reader.readFrom(0).text
}

/**
 * Spawn a graphlint CLI invocation with collected stdio and await its exit.
 *
 * Hardening rules learned from the first prototype:
 * - force UTF-8 (`PYTHONIOENCODING`) so localized code pages cannot garble output;
 * - wire the caller's AbortSignal so the cooperative tool timeout can terminate the tree;
 * - cap the exit wait so a wedged build cannot hang the tool turn;
 * - never shell-interpret argv.
 */
export async function runGraphlint(
  subprocess: SubprocessService,
  timer: TimerLike,
  argv: string[],
  cwd: string,
  limits: RunLimits = DEFAULT_LIMITS,
  signal?: AbortSignal,
): Promise<RunOutcome> {
  const handle = subprocess.spawn({
    argv,
    cwd,
    stdio: {
      stdin: 'ignore',
      stdout: { maxBytes: 1_048_576 },
      stderr: { maxBytes: 262_144 },
    },
    graceMs: limits.graceMs,
    signal,
    env: { PYTHONIOENCODING: 'utf-8' },
  })
  const outcome = await withTimeout(timer, handle.done, limits.doneCapMs)
  if (outcome === 'timeout') {
    handle.terminate()
    return { exitCode: null, stdout: '', stderr: '', timedOut: true }
  }
  return {
    exitCode: outcome.exitCode,
    stdout: readAll(handle.collected?.stdout),
    stderr: readAll(handle.collected?.stderr),
    timedOut: false,
  }
}
