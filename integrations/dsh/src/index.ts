/**
 * dsh-graphlint — DeepSeek Harness plugin bundle for the graphlint
 * dead-code detection CLI.
 *
 * Default export: the Cordis plugin whose apply() registers the skill and the
 * three model-facing tools. Registrations are fiber-scoped (the DSH tools and
 * skills registries clean them up on plugin dispose), so no manual teardown
 * is needed here.
 *
 * Optional, zero-dependency compatibility with dsh-multi-folder: every tool
 * silently probes `ctx.get('multiFolder')` at call time (never declared in
 * inject), so the session's configured secondary working directories become
 * valid analysis roots. Absent or failing, the bundle behaves exactly as if
 * multi-folder did not exist — see `secondary.ts`.
 */

import type { PluginContext } from './types.js'
import { registerGraphlintSkill } from './skill.js'
import { registerQueryTool } from './tools/query.js'
import { registerBuildTool } from './tools/build.js'
import { registerConfigTool } from './tools/config.js'

export const name = 'dsh-graphlint'

export const inject = ['tools', 'subprocess', 'fs', 'skills', 'jobs', 'timer']

export function apply(ctx: PluginContext): void {
  registerGraphlintSkill(ctx)
  registerQueryTool(ctx)
  registerBuildTool(ctx)
  registerConfigTool(ctx)
}
