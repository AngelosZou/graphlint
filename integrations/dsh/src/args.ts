/**
 * argv builders for the graphlint CLI.
 *
 * All invocations force `--json --lang en` (JSON-only output in English) so
 * the runner never has to deal with localized console text or non-UTF-8
 * code-page output on Windows.
 */

export interface QueryOptions {
  rootDir: string
  warnTypes?: string
  includeTests?: boolean
  graphId?: number
  publicAsEntry?: boolean
}

export function queryArgv(exe: string, options: QueryOptions): string[] {
  const argv = [exe, 'query', '--json', '--lang', 'en']
  if (typeof options.warnTypes === 'string' && options.warnTypes.trim().length > 0) {
    argv.push('--warn-types', options.warnTypes.trim())
  }
  if (options.includeTests === true) argv.push('--include-tests')
  if (options.publicAsEntry === true) argv.push('--public-as-entry')
  if (typeof options.graphId === 'number') argv.push('--graph-id', String(options.graphId))
  argv.push('--root-dir', options.rootDir)
  return argv
}

/**
 * `graphlint build` has no --root-dir flag; it analyzes its own cwd. The
 * caller MUST spawn it with cwd set to the guarded analysis root.
 */
export function buildArgv(exe: string, force: boolean): string[] {
  const argv = [exe, 'build', '--lang', 'en']
  if (force) argv.push('--force')
  return argv
}

export type ConfigAction = 'show' | 'get' | 'set'

/**
 * `graphlint config` also reads .graphlint/config.json from its cwd; the
 * caller MUST spawn it with cwd set to the guarded analysis root.
 */
export function configArgv(exe: string, action: ConfigAction, key?: string, value?: string): string[] {
  const argv = [exe, 'config', '--lang', 'en', action]
  if (action === 'get') argv.push('--key', key ?? '')
  if (action === 'set') {
    argv.push('--key', key ?? '', '--value', value ?? '')
  }
  return argv
}
