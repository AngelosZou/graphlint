/**
 * Optional, automatic compatibility with the dsh-multi-folder plugin —
 * with NO dependency relationship.
 *
 * At call time each tool silently probes `ctx.get('multiFolder')`: the
 * service dsh-multi-folder provides (a plain object with a read-only
 * `list(workspace)` method returning `{ dirs }`). When the service is
 * absent, its `list` is missing, or it throws, every helper here is a
 * no-op — the plugin behaves exactly as if multi-folder did not exist:
 * no extra context, no user-visible difference, and `multiFolder` is never
 * declared in this plugin's inject list.
 *
 * When multi-folder IS configured, the session's secondary working
 * directories join the primary workspace as allowed analysis roots, so
 * graphlint can index and query a project the user granted to the session
 * even though it lives outside the session working directory.
 * @module dsh-graphlint/secondary
 */

/**
 * The slice of the Cordis context this probe needs: the optional service
 * lookup. Declared structurally so the probe compiles (and stays meaningful)
 * against the plugin's own minimal host surface in `types.ts`.
 */
export interface ServiceLookup {
  get?(name: string): unknown
}

/** Shape of the service `dsh-multi-folder` provides (read-only on our side). */
export interface MultiFolderService {
  list(workspace: string): unknown
}

/**
 * Configured secondary working directories for the session workspace, or []
 * when the multi-folder plugin is not installed/configured.
 */
export async function secondaryDirs(
  ctx: ServiceLookup | undefined,
  workspace: string,
): Promise<string[]> {
  const probe = ctx?.get
  if (typeof probe !== 'function') return []
  const service = probe.call(ctx, 'multiFolder') as MultiFolderService | undefined
  if (service === undefined || service === null) return []
  const list = service.list
  if (typeof list !== 'function') return []
  try {
    const result = (await list.call(service, workspace)) as { dirs?: unknown } | undefined
    const dirs = result && typeof result === 'object' && Array.isArray(result.dirs) ? result.dirs : []
    return dirs.filter((dir): dir is string => typeof dir === 'string' && dir.length > 0)
  } catch {
    // absent, incompatible, or failing — behave as if multi-folder were not installed
    return []
  }
}
