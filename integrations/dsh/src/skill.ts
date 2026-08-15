import type { PluginContext, SkillRegistration } from './types.js'
import { SKILL_BODY } from './skill-content.generated.js'

// The canonical skill body is embedded at build time from graphlint/skill.md
// (see scripts/generate-skill.mjs and test/skill-sync.test.ts); the
// DSH-specific tool mapping below is the only plugin-local content.

const DSH_TOOLS = `## Tools in this environment
- \`graphlint_query\` — runs \`graphlint query\` with structured results. Auto-rebuilds the index incrementally on first use; prefer it over an explicit build.
- \`graphlint_build\` — \`graphlint build\` as a **background job** (poll with \`job_output\`). Use only when query results look wrong or stale.
- \`graphlint_config\` — \`graphlint config\` operations: show/get/set the project's \`.graphlint/config.json\`, add/remove custom entry rules and excludes.

Tool parameters mirror the CLI flags above (\`root_dir\`, \`warn_types\`, \`include_tests\`, \`graph_id\`, \`public_as_entry\`, \`force\`). \`root_dir\` must stay inside the session working directory (the default) — scanning a high-level root can block for minutes.
`

const GRAPHLINT_SKILL: SkillRegistration = {
  name: 'graphlint',
  description: 'Dead-code detection for AI-generated codebases via the graphlint dependency-graph analyzer.',
  whenToUse:
    'After code modifications, or before analyzing a codebase, to find dead code, circular references, unused imports and other warnings.',
  invocation: { modelInvocable: true, userInvocable: true },
  content: SKILL_BODY + DSH_TOOLS,
}

export function registerGraphlintSkill(ctx: PluginContext): void {
  ctx.skills.register(GRAPHLINT_SKILL)
}
