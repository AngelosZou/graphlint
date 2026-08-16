import type { PluginContext, SkillRegistration } from './types.js'
import { SKILL_BODY } from './skill-content.generated.js'

// The canonical skill body is embedded at build time from graphlint/skill.md
// (see scripts/generate-skill.mjs and test/skill-sync.test.ts). In the DSH
// environment graphlint is exposed as TOOLS, which are more robust than shell
// invocations, so a tool-first section leads the skill; the canonical CLI body
// follows as reference. This section is the only plugin-local content.

const DSH_INTRO = `## How to use graphlint in this environment
graphlint is exposed as tools — **prefer the tools over shelling out to the CLI**: they run inside the session working directory, return structured results, and refuse unsafe roots.

- \`graphlint_query\` — replaces \`graphlint query\`. Common arguments: \`root_dir\`, \`warn_types\` (e.g. "dead_code,circular_ref"), \`graph_id\`, \`exclude_clean\`, \`include_tests\`, \`public_as_entry\`. Auto-rebuilds the index incrementally; use it after edits and before analyzing a codebase.
- \`graphlint_build\` — \`graphlint build --force\` as a **background job** (poll with \`job_output\`). Use only when \`graphlint_query\` results look wrong or stale.
- \`graphlint_config\` — \`graphlint config\` operations: \`show\`/\`get\`/\`set\`, plus \`add-entry-rule\` (\`rule_json\`), \`remove-entry-rule\` (\`name\`), \`add-exclude\`/\`remove-exclude\` (\`exclude_pattern\`) for custom entry rules.

\`root_dir\` must stay inside the session working directory (the default) — scanning a high-level root can block for minutes. Flags the tools do not expose (e.g. \`--sort-by\`, \`--fail-on\`) require running \`graphlint\` directly in a shell.

`

const GRAPHLINT_SKILL: SkillRegistration = {
  name: 'graphlint',
  description: 'Dead-code detection for AI-generated codebases via the graphlint dependency-graph analyzer.',
  whenToUse:
    'After code modifications, or before analyzing a codebase, to find dead code, circular references, unused imports and other warnings.',
  source: 'custom',
  invocation: { modelInvocable: true, userInvocable: true },
  content: DSH_INTRO + SKILL_BODY,
}

export function registerGraphlintSkill(ctx: PluginContext): void {
  ctx.skills.register(GRAPHLINT_SKILL)
}
