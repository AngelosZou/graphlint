import { join } from 'node:path'

import type { FsService, SubprocessService } from './types.js'

const WINDOWS_BINS = [
  'env\\Scripts\\graphlint.exe',
  '.venv\\Scripts\\graphlint.exe',
  'venv\\Scripts\\graphlint.exe',
]

const POSIX_BINS = ['env/bin/graphlint', '.venv/bin/graphlint', 'venv/bin/graphlint']

/**
 * Locate a runnable graphlint CLI.
 *
 * Resolution order: the `graphlint` console script on PATH, then the common
 * project-local virtualenv script locations under the analysis root. Returns
 * null when graphlint is not installed anywhere reachable.
 */
export async function resolveGraphlint(
  subprocess: SubprocessService,
  fs: FsService | undefined,
  rootDir: string,
): Promise<string | null> {
  try {
    const exe = await subprocess.resolveExecutable('graphlint')
    if (exe) return exe
  } catch {
    /* PATH lookup failed; fall through to virtualenv probes */
  }
  const bins = process.platform === 'win32' ? WINDOWS_BINS : POSIX_BINS
  for (const rel of bins) {
    const candidate = join(rootDir, rel)
    try {
      const target = await fs?.resolve(candidate, { cwd: rootDir })
      if (target === undefined) continue
      const info = await fs?.stat(target)
      if (info) return candidate
    } catch {
      /* probe failed */
    }
  }
  return null
}
