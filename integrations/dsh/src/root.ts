import { isAbsolute, relative, resolve, sep } from 'node:path'

import type { ToolExecutionLike } from './types.js'

/**
 * Absolute working directory the executing session was created in.
 *
 * This is the DSH framework keyword for the session workspace; it is NOT the
 * same as the deployment-wide sandbox workspace root. Falling back to
 * `process.cwd()` keeps the value defined even for executors that omit the
 * agent chain.
 */
export function sessionCwd(exec: ToolExecutionLike | undefined): string {
  const header = exec?.agent?.session?.header
  if (header && typeof header.cwd === 'string' && header.cwd.length > 0) return header.cwd
  return process.cwd()
}

/** Raised when a requested analysis root escapes the session working directory. */
export class RootOutsideSessionError extends Error {
  constructor(
    public readonly requested: string,
    public readonly sessionRoot: string,
  ) {
    super(
      `root_dir must stay inside the session working directory (${sessionRoot}); got ${requested}. ` +
        'Scanning a high-level root (e.g. a user home directory) builds a huge index and can block for many minutes.',
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
  const root = resolve(requested && requested.trim().length > 0 ? requested : sessionRoot)
  if (isWithin(sessionRoot, root)) return root
  throw new RootOutsideSessionError(root, sessionRoot)
}
