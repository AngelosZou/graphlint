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
  excludeClean?: boolean
}

export function queryArgv(exe: string, options: QueryOptions): string[] {
  const argv = [exe, 'query', '--json', '--lang', 'en']
  if (typeof options.warnTypes === 'string' && options.warnTypes.trim().length > 0) {
    argv.push('--warn-types', options.warnTypes.trim())
  }
  if (options.includeTests === true) argv.push('--include-tests')
  if (options.publicAsEntry === true) argv.push('--public-as-entry')
  if (options.excludeClean === true) argv.push('--exclude-clean')
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

export type ConfigAction =
  | 'show'
  | 'get'
  | 'set'
  | 'add-entry-rule'
  | 'remove-entry-rule'
  | 'add-exclude'
  | 'remove-exclude'

export interface ConfigParams {
  key?: string
  value?: string
  ruleJson?: string
  name?: string
  excludePattern?: string
}

/**
 * `graphlint config` also reads .graphlint/config.json from its cwd; the
 * caller MUST spawn it with cwd set to the guarded analysis root.
 */
export function configArgv(exe: string, action: ConfigAction, params: ConfigParams = {}): string[] {
  const argv = [exe, 'config', '--lang', 'en', action]
  if (action === 'get') argv.push('--key', params.key ?? '')
  if (action === 'set') {
    argv.push('--key', params.key ?? '', '--value', params.value ?? '')
  }
  if (action === 'add-entry-rule') argv.push('--rule-json', params.ruleJson ?? '')
  if (action === 'remove-entry-rule') argv.push('--name', params.name ?? '')
  if (action === 'add-exclude' || action === 'remove-exclude') {
    argv.push('--exclude-pattern', params.excludePattern ?? '')
  }
  return argv
}
