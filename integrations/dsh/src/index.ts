/**
 * dsh-graphlint — DeepSeek Harness plugin bundle for the graphlint
 * dead-code detection CLI.
 *
 * Default export: the Cordis plugin whose apply() registers the skill and the
 * three model-facing tools. Registrations are fiber-scoped (the DSH tools and
 * skills registries clean them up on plugin dispose), so no manual teardown
 * is needed here.
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
