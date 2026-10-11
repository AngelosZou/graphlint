import { isAbsolute, relative, resolve, sep } from 'node:path'

import type { AgentLike, WorkingDirectoryService } from './types.js'

/**
 * What {@link sessionCwd} and {@link resolveSessionCwd} read from one tool
 * execution. Structural on purpose: it is satisfied by the engine's
 * `ToolRunContext` and by the plain objects the unit tests build, so the
 * functions stay testable without importing the whole execution type.
 */
export interface SessionContext {
  readonly agent?: AgentLike | undefined
  readonly signal?: AbortSignal | undefined
}

/**
 * Absolute working directory the executing session was created in.
 *
 * This is the DSH framework keyword for the session workspace; it is NOT the
 * same as the deployment-wide sandbox workspace root. Falling back to
 * `process.cwd()` keeps the value defined even for executors that omit the
 * agent chain.
 *
 * This is the SYNCHRONOUS fallback. Prefer {@link resolveSessionCwd}, which
 * asks the supported `workingDirectory` seam first; this one reads the live
 * Agent's session header directly (the augmented runtime shape) and exists for
 * the path where no working-directory service is mounted.
 */
export function sessionCwd(exec: SessionContext | undefined): string {
  const header = exec?.agent?.session?.header
  if (header && typeof header.cwd === 'string' && header.cwd.length > 0) return header.cwd
  return process.cwd()
}

/**
 * Resolve the analysis root for one tool call.
 *
 * Order: the `workingDirectory` service (the seam that owns the session's
 * effective directory and can repair a deleted project), then the session
 * header's original cwd, then the process directory.
 *
 * The service is read through `ctx.get` rather than declared in `inject`, so a
 * deployment without it keeps working. `ensure()` runs against the live runtime
 * Agent (`exec.agent`), which the published `Agent` face describes as `{ id }`
 * alone; the value is forwarded unchanged and the seam sees the real
 * augmented object.
 */
export async function resolveSessionCwd(
  exec: SessionContext | undefined,
  lookup?: (name: string) => unknown,
): Promise<string> {
  const agent = exec?.agent
  if (agent !== undefined && lookup !== undefined) {
    const service = lookup('workingDirectory') as WorkingDirectoryService | undefined
    if (service && typeof service.ensure === 'function') {
      try {
        const directory = await service.ensure(agent, exec?.signal)
        if (typeof directory === 'string' && directory.length > 0) return directory
      } catch {
        // The seam refused (no live agent, deleted project, cancellation). Fall
        // back to the header/process directory rather than failing the call:
        // the root guard still bounds whatever we return.
      }
    }
  }
  return sessionCwd(exec)
}

/**
 * Model-facing sentence naming the extra roots a tool call may also target.
 * Shared by the tool descriptions so the three tools say the same thing.
 */
export const SECONDARY_ROOT_NOTE =
  "A root inside one of the session's secondary working directories (dsh-multi-folder) is accepted as well."

/** Raised when a requested analysis root escapes every allowed root. */
export class RootOutsideSessionError extends Error {
  constructor(
    public readonly requested: string,
    public readonly sessionRoot: string,
    public readonly extraRoots: readonly string[] = [],
  ) {
    const configured =
      extraRoots.length === 0
        ? ''
        : " or inside one of the session's secondary working directories (" + extraRoots.join(', ') + ')'
    const remedy =
      extraRoots.length === 0
        ? ''
        : " Add the directory with the user's /multi-folder command to make it a valid analysis root."
    super(
      `root_dir must stay inside the session working directory (${sessionRoot})${configured}; got ${requested}. ` +
        'Scanning a high-level root (e.g. a user home directory) builds a huge index and can block for many minutes.' +
        remedy,
    )
    this.name = 'RootOutsideSessionError'
  }
}

/** True when `root` equals `base` or lies inside it (case-insensitive on Windows). */
export function isWithin(base: string, root: string): boolean {
  const rel = relative(base, root)
  if (rel === '') return true
  const normalized = process.platform === 'win32' ? rel.toLowerCase() : rel
  return normalized !== '..' && !normalized.startsWith('..' + sep) && !isAbsolute(normalized)
}

/**
 * Resolve the requested analysis root and refuse anything outside the session
 * working directory.
 *
 * graphlint indexes every source file under its root; letting a tool call
 * point at a high-level directory (home dir, drive root) turns a fast
 * incremental query into a multi-minute first-time index build. The guard
 * fails fast with a clear message instead of blocking the turn.
 */
export function guardRoot(requested: string | undefined, sessionRoot: string): string {
  return guardAllowedRoot(requested, sessionRoot, [])
}

/**
 * Multi-root guard: the primary workspace plus optional extra roots (the
 * dsh-multi-folder secondary working directories, when that plugin is
 * configured for this session). Relative paths resolve against the primary
 * workspace; an absolute target is accepted when it lands inside ANY allowed
 * root. With no extra roots this is exactly {@link guardRoot}.
 *
 * An extra root is a directory the USER granted the session through
 * `/multi-folder`, so it is trusted exactly like the primary workspace: the
 * guard's purpose is to keep the model from pointing graphlint at an
 * unintended drive-wide root, not to second-guess a configured grant.
 */
export function guardAllowedRoot(
  requested: string | undefined,
  sessionRoot: string,
  extraRoots: readonly string[] = [],
): string {
  const primary = resolve(sessionRoot)
  const wanted = requested !== undefined && requested.trim().length > 0 ? requested : primary
  const root = resolve(primary, wanted)
  if (isWithin(primary, root)) return root
  for (const extra of extraRoots) {
    if (isWithin(resolve(extra), root)) return root
  }
  throw new RootOutsideSessionError(root, primary, extraRoots)
}
